"""Expose HTTP endpoints and response models for improvement plans."""

import hmac
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request

from internal.http.ms_auth_authorization import ensure_plan_belongs_to_principal
from internal.http.ms_auth_dependencies import MsAuth, require_ms_auth_principal
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from improvement_plan.constants import CATEGORY_CLASSIFICATIONS
from improvement_plan.database.repository import Repository
from improvement_plan.entity import ExtractedInventory
from improvement_plan.improvement_plan import IService, MalformedPlanError
from improvement_plan.service import Service

from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

router = APIRouter(tags=["Reports"])

INTERNAL_AUTHENTICATION_KEY_ENV = "INTERNAL_AUTHENTICATION_KEY"

CategoryClassification = Literal["UPSTREAM", "DOWNSTREAM"]


def require_inventory_report_authentication_key(
    authentication_key: str | None = Header(None, alias="authentication-key"),
) -> None:
    """Reject requests whose authentication-key header does not match the configured secret."""
    expected = os.environ.get(INTERNAL_AUTHENTICATION_KEY_ENV, "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Inventory report authentication is not configured.",
        )
    if authentication_key is None:
        raise HTTPException(status_code=401, detail="Missing authentication key.")
    if not hmac.compare_digest(authentication_key, expected):
        raise HTTPException(status_code=401, detail="Invalid authentication key.")


class CatalogItemData(BaseModel):
    id: int = Field(..., description="Catalog identifier used as a foreign key on extracted emissions.", json_schema_extra={"example": 1})
    name: str = Field(..., description="Catalog display name.", json_schema_extra={"example": "CO2"})

    model_config = ConfigDict(frozen=True)


class CategoryCatalogItemData(BaseModel):
    id: int = Field(..., description="Category identifier used as a foreign key on extracted emissions.", json_schema_extra={"example": 1})
    name: str = Field(..., description="Category display name.", json_schema_extra={"example": "Combustão estacionária"})
    classification: CategoryClassification | None = Field(None, description="Whether the category is upstream, downstream, or unclassified.", json_schema_extra={"example": None})

    model_config = ConfigDict(frozen=True)


class ReportRequestData(BaseModel):
    id_external_context_inventory: int = Field(..., description="External inventory identifier analyzed and stored on the resulting plan.", json_schema_extra={"example": 502})
    inventory: str = Field(..., description="Inventory content as Markdown.", json_schema_extra={"example": "## Escopo 1"})
    id_external_user: int = Field(..., description="External user identifier responsible for the report.", json_schema_extra={"example": 12345})
    id_external_company: int = Field(..., description="External company identifier that owns the inventory and resulting plan.", json_schema_extra={"example": 90})
    gases: list[CatalogItemData] = Field(..., description="Gas catalog in force for this analysis.")
    scopes: list[CatalogItemData] = Field(..., description="Scope catalog in force for this analysis.")
    categories: list[CategoryCatalogItemData] = Field(..., description="Category catalog in force for this analysis.")

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def catalog_identifiers_are_unique(self):
        """Reject catalogs that repeat an identifier, which the Aeko contract cannot consume."""
        for name, items in (
            ("gases", self.gases),
            ("scopes", self.scopes),
            ("categories", self.categories),
        ):
            identifiers = [item.id for item in items]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} contains duplicate ids.")
            if name == "categories":
                for item in items:
                    if item.classification is not None and item.classification not in CATEGORY_CLASSIFICATIONS:
                        raise ValueError("categories classification is invalid.")
        return self


class InventoryEmissionData(BaseModel):
    quantity_co2e: float = Field(..., description="Emission or reduction quantity in tCO2e.", json_schema_extra={"example": 12400.0})
    methodology_description: str | None = Field(None, description="How the quantity was obtained.", json_schema_extra={"example": "stationary combustion"})
    supplier_data_percentage: float | None = Field(None, description="Share of the quantity backed by supplier data.", json_schema_extra={"example": None})
    gas: int | None = Field(None, description="Gas catalog identifier.", json_schema_extra={"example": 1})
    scope: int | None = Field(None, description="Scope catalog identifier.", json_schema_extra={"example": 1})
    category: int | None = Field(None, description="Category catalog identifier.", json_schema_extra={"example": None})
    is_upstream: bool | None = Field(None, description="Whether the emission is classified as upstream.", json_schema_extra={"example": None})
    is_reduction: bool = Field(..., description="Whether the row is a reduction rather than an emission.", json_schema_extra={"example": False})

    model_config = ConfigDict(frozen=True)


class ExtractedInventoryData(BaseModel):
    description: str | None = Field(None, description="Short description of the analyzed inventory.", json_schema_extra={"example": "Boiler-dominated inventory"})
    start_period: str | None = Field(None, description="Start of the inventory period.", json_schema_extra={"example": "2025-01-01"})
    end_period: str | None = Field(None, description="End of the inventory period.", json_schema_extra={"example": "2025-12-31"})
    emissions: list[InventoryEmissionData] = Field(..., description="Emission and reduction rows extracted from the inventory.")

    model_config = ConfigDict(frozen=True)


class ImprovementPlanReportData(BaseModel):
    defined_problem: str = Field(..., description="Problem the analysis identified.", json_schema_extra={"example": "high scope 1 emissions"})
    solving_method: str = Field(..., description="What the plan proposes doing about it.", json_schema_extra={"example": "replace the boiler fleet"})
    reasoning: str = Field(..., description="Why that method addresses that problem.", json_schema_extra={"example": "direct combustion dominates the inventory"})

    model_config = ConfigDict(frozen=True)


def get_improvement_plan_service(request: Request) -> IService:
    """Build the plan service from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")

    from cmd.api.integrations.mcp.chroma_mcp import _upsert_improvement_plan_problem

    return Service(Repository(database), chroma_indexer=_upsert_improvement_plan_problem)


def extracted_inventory_data(inventory: ExtractedInventory) -> ExtractedInventoryData:
    """Map a domain structured inventory onto the HTTP response model."""
    return ExtractedInventoryData(
        description=inventory.description,
        start_period=inventory.start_period,
        end_period=inventory.end_period,
        emissions=[
            InventoryEmissionData(
                quantity_co2e=item.quantity_co2e,
                methodology_description=item.methodology_description,
                supplier_data_percentage=item.supplier_data_percentage,
                gas=item.gas,
                scope=item.scope,
                category=item.category,
                is_upstream=item.is_upstream,
                is_reduction=item.is_reduction,
            )
            for item in inventory.emissions
        ],
    )


def _http_status_for_value_error(exc: ValueError) -> int:
    """Map domain validation errors to 404, 403, or 400."""
    message = str(exc).lower()
    if "not found" in message:
        return 404
    if "another company" in message or "does not belong" in message:
        return 403
    return 400


@router.post(
    "/ai/report",
    response_model=ExtractedInventoryData,
    summary="Analyze an inventory and return the structured extraction",
    description=(
        "Accepts inventory Markdown and the catalogs in force, runs them through the Aeko "
        "analyst flow with the current plan for that inventory as context, stores the new "
        "plan, and returns the structured inventory for Postgres persistence."
    ),
    dependencies=[Depends(require_inventory_report_authentication_key)],
    responses={
        200: {
            "description": "Structured inventory extracted from the analysis.",
            "content": {
                "application/json": {
                    "example": {
                        "description": "Boiler-dominated inventory",
                        "start_period": "2025-01-01",
                        "end_period": "2025-12-31",
                        "emissions": [
                            {
                                "quantity_co2e": 12400.0,
                                "methodology_description": "stationary combustion",
                                "supplier_data_percentage": None,
                                "gas": 1,
                                "scope": 1,
                                "category": None,
                                "is_upstream": None,
                                "is_reduction": False,
                            }
                        ],
                    }
                }
            },
        },
        400: {"description": "The inventory Markdown is empty or a domain catalog rule was rejected."},
        404: {"description": "No user exists for the supplied external identifier."},
        502: {"description": "The analysis produced no plan or structured inventory in the expected shape."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "The Aeko SDK is not initialized or an unexpected error occurred."},
    },
)
async def input_report(
    request: Request,
    body: ReportRequestData,
    service: IService = Depends(get_improvement_plan_service),
) -> ExtractedInventoryData:
    """Generate a structured inventory in a worker thread and translate domain errors to HTTP responses."""
    aeko_inventory_analyzer_factory = request.app.state._state.get("aeko_inventory_analyzer_factory")

    if not aeko_inventory_analyzer_factory:
        raise HTTPException(status_code=500, detail="Aeko SDK is not initialized")

    try:
        inventory = await run_in_threadpool(
            service.input_inventory,
            body.id_external_context_inventory,
            body.inventory,
            body.id_external_user,
            body.id_external_company,
            [item.model_dump() for item in body.gases],
            [item.model_dump() for item in body.scopes],
            [item.model_dump() for item in body.categories],
            UserService(UserRepository(request.app.state.db)),
            aeko_inventory_analyzer_factory,
        )
        return extracted_inventory_data(inventory)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc
    except MalformedPlanError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error processing report: {exc}") from exc


@router.get(
    "/ai/report/{id_external_inventory}",
    response_model=ImprovementPlanReportData,
    summary="Get the textual improvement plan for an inventory",
    description="Returns the stored improvement plan for the external inventory identifier.",
    dependencies=[Depends(require_ms_auth_principal)],
    responses={
        200: {
            "description": "Textual improvement plan found.",
            "content": {
                "application/json": {
                    "example": {
                        "defined_problem": "high scope 1 emissions",
                        "solving_method": "replace the boiler fleet",
                        "reasoning": "direct combustion dominates the inventory",
                    }
                }
            },
        },
        404: {"description": "No improvement plan exists for the supplied inventory identifier."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_report(
    principal: MsAuth,
    id_external_inventory: int = Path(..., description="External inventory identifier whose plan should be returned.", examples=[502]),
    service: IService = Depends(get_improvement_plan_service),
) -> ImprovementPlanReportData:
    """Retrieve the stored textual plan for an inventory."""
    try:
        plan = service.get_by_id_external_inventory(id_external_inventory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving report: {exc}") from exc
    ensure_plan_belongs_to_principal(principal, plan)
    return ImprovementPlanReportData(
        defined_problem=plan.defined_problem,
        solving_method=plan.method,
        reasoning=plan.reasoning,
    )
