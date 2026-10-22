"""Verify calculator behavior and error handling."""

import ast

import pytest
from langchain_core.tools import Tool

from cmd.api.tools import calculator


def evaluate(expression):
    """Evaluate an expression through the calculator tool."""
    return calculator._evaluate(ast.parse(expression, mode="eval").body)


def test_parse_expression_drops_surrounding_whitespace():
    """Verify that parse expression drops surrounding whitespace."""
    assert calculator._parse_expression("  2 + 2  ") == "2 + 2"


def test_parse_expression_accepts_an_expression_spelled_over_several_lines():
    """Verify that parse expression accepts an expression spelled over several lines."""
    assert (
        calculator._parse_expression("(1200 * 2.68)\n+ 300") == "(1200 * 2.68)\n+ 300"
    )


@pytest.mark.parametrize("expression", ["", "   ", "\n", None, 42, ["2 + 2"]])
def test_parse_expression_rejects_anything_that_is_not_an_expression(expression):
    """Verify that parse expression rejects anything that is not an expression."""
    with pytest.raises(ValueError) as error:
        calculator._parse_expression(expression)

    assert repr(expression) in str(error.value)


def test_parse_expression_rejects_an_expression_longer_than_the_cap():
    """Verify that parse expression rejects an expression longer than the cap."""
    with pytest.raises(ValueError) as error:
        calculator._parse_expression("1+" * calculator.CALCULATOR_MAX_EXPRESSION_LENGTH)

    assert str(calculator.CALCULATOR_MAX_EXPRESSION_LENGTH) in str(error.value)


def test_parse_expression_accepts_an_expression_exactly_at_the_cap():
    """Verify that parse expression accepts an expression exactly at the cap."""
    expression = "1" * calculator.CALCULATOR_MAX_EXPRESSION_LENGTH

    assert calculator._parse_expression(expression) == expression


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 3", 5),
        ("10 - 4", 6),
        ("6 * 7", 42),
        ("9 / 2", 4.5),
        ("9 // 2", 4),
        ("9 % 2", 1),
        ("2 ** 10", 1024),
    ],
)
def test_evaluate_computes_every_allowed_operator(expression, expected):
    """Verify that evaluate computes every allowed operator."""
    assert evaluate(expression) == expected


def test_evaluate_respects_precedence_and_parentheses():
    """Verify that evaluate respects precedence and parentheses."""
    assert evaluate("2 + 3 * 4") == 14
    assert evaluate("(2 + 3) * 4") == 20


def test_evaluate_handles_the_unary_signs():
    """Verify that evaluate handles the unary signs."""
    assert evaluate("-5") == -5
    assert evaluate("+5") == 5
    assert evaluate("-(2 + 3)") == -5


def test_evaluate_reads_decimals_and_scientific_notation():
    """Verify that evaluate reads decimals and scientific notation."""
    assert evaluate("2.5 * 4") == 10.0
    assert evaluate("1.2e3") == 1200.0


def test_evaluate_computes_an_emission_the_way_an_analyst_writes_it():
    """Verify that evaluate computes an emission the way an analyst writes it."""
    assert evaluate("(1200 * 2.68) / 1000") == pytest.approx(3.216)


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("abs(-7)", 7),
        ("round(3.14159, 2)", 3.14),
        ("min(4, 2, 9)", 2),
        ("max(4, 2, 9)", 9),
        ("sum([1, 2, 3])", 6),
        ("sqrt(16)", 4.0),
        ("log(100, 10)", pytest.approx(2.0)),
    ],
)
def test_evaluate_computes_every_allowed_function(expression, expected):
    """Verify that evaluate computes every allowed function."""
    assert evaluate(expression) == expected


def test_evaluate_sums_a_tuple_as_well_as_a_list():
    """Verify that evaluate sums a tuple as well as a list."""
    assert evaluate("sum((1, 2, 3))") == 6


def test_evaluate_nests_functions_inside_arithmetic():
    """Verify that evaluate nests functions inside arithmetic."""
    assert evaluate("round(sum([10.4, 20.6]) / 2, 1)") == 15.5


def test_evaluate_rounds_the_way_python_rounds():
    """Verify that evaluate rounds the way python rounds."""
    assert evaluate("round(15.45, 1)") == 15.4


def test_evaluate_refuses_a_bare_name():
    """Verify that evaluate refuses a bare name."""
    with pytest.raises(ValueError) as error:
        evaluate("pi * 2")

    assert "pi" in str(error.value)


def test_evaluate_refuses_an_attribute_lookup():
    """Verify that evaluate refuses an attribute lookup."""
    with pytest.raises(ValueError) as error:
        evaluate("(2).__class__")

    assert "__class__" in str(error.value)


def test_evaluate_refuses_a_function_it_does_not_know():
    """Verify that evaluate refuses a function it does not know."""
    with pytest.raises(ValueError) as error:
        evaluate("__import__('os')")

    assert "__import__" in str(error.value)


def test_evaluate_refuses_a_dotted_call():
    """Verify that evaluate refuses a dotted call."""
    with pytest.raises(ValueError) as error:
        evaluate("math.sqrt(2)")

    assert "math.sqrt" in str(error.value)


def test_evaluate_naming_a_refused_function_lists_the_ones_it_knows():
    """Verify that evaluate naming a refused function lists the ones it knows."""
    with pytest.raises(ValueError) as error:
        evaluate("factorial(5)")

    message = str(error.value)
    assert all(name in message for name in calculator.CALCULATOR_FUNCTIONS)


def test_evaluate_refuses_keyword_arguments():
    """Verify that evaluate refuses keyword arguments."""
    with pytest.raises(ValueError) as error:
        evaluate("round(3.14159, ndigits=2)")

    assert "ndigits" in str(error.value)


@pytest.mark.parametrize(
    "expression",
    [
        "'os'",
        "True",
        "None",
        "[1, 2]",
        "{'a': 1}",
        "{1, 2}",
        "1 if 2 else 3",
        "2 > 1",
        "1 and 2",
        "not 1",
        "1 & 2",
        "[x for x in [1]]",
        "lambda: 1",
        "(y := 2)",
        "f'{1}'",
        "...",
    ],
)
def test_evaluate_refuses_everything_that_is_not_arithmetic(expression):
    """Verify that evaluate refuses everything that is not arithmetic."""
    with pytest.raises(ValueError):
        evaluate(expression)


def test_evaluate_refuses_a_division_by_zero():
    """Verify that evaluate refuses a division by zero."""
    with pytest.raises(ValueError) as error:
        evaluate("1 / 0")

    assert "zero" in str(error.value)


def test_evaluate_refuses_an_exponent_that_would_not_finish():
    """Verify that evaluate refuses an exponent that would not finish."""
    with pytest.raises(ValueError) as error:
        evaluate(f"2 ** {calculator.CALCULATOR_MAX_EXPONENT + 1}")

    assert str(calculator.CALCULATOR_MAX_EXPONENT) in str(error.value)


def test_evaluate_allows_an_exponent_at_the_cap():
    """Verify that evaluate allows an exponent at the cap."""
    assert evaluate(f"1 ** {calculator.CALCULATOR_MAX_EXPONENT}") == 1


def test_evaluate_refuses_a_result_that_left_the_real_numbers():
    """Verify that evaluate refuses a result that left the real numbers."""
    with pytest.raises(ValueError) as error:
        evaluate("(-8) ** 0.5")

    assert "real" in str(error.value)


def test_evaluate_refuses_a_result_too_large_to_represent():
    """Verify that evaluate refuses a result too large to represent."""
    with pytest.raises(ValueError) as error:
        evaluate("1.5e308 * 10")

    assert "large" in str(error.value)


def test_evaluate_refuses_a_power_that_overflows_the_float():
    """Verify that evaluate refuses a power that overflows the float."""
    with pytest.raises(ValueError) as error:
        evaluate("10.0 ** 400")

    assert "large" in str(error.value)


def test_evaluate_refuses_a_maths_call_outside_its_domain():
    """Verify that evaluate refuses a maths call outside its domain."""
    with pytest.raises(ValueError) as error:
        evaluate("sqrt(-1)")

    assert "sqrt" in str(error.value)


def test_evaluate_refuses_a_maths_call_with_the_wrong_number_of_arguments():
    """Verify that evaluate refuses a maths call with the wrong number of arguments."""
    with pytest.raises(ValueError) as error:
        evaluate("round(1, 2, 3)")

    assert "round" in str(error.value)


def test_calculate_answers_with_the_number_as_text():
    """Verify that calculate answers with the number as text."""
    assert calculator._calculate("2 + 2") == "4"


def test_calculate_hides_binary_floating_point_noise():
    """Verify that calculate hides binary floating point noise."""
    assert calculator._calculate("1200 * 2.68") == "3216"


def test_calculate_keeps_the_decimals_that_carry_meaning():
    """Verify that calculate keeps the decimals that carry meaning."""
    assert calculator._calculate("1 / 3") == "0.3333333333"


def test_calculate_rounds_to_the_documented_number_of_places():
    """Verify that calculate rounds to the documented number of places."""
    places = calculator.CALCULATOR_DECIMAL_PLACES
    answer = calculator._calculate("2 / 3")

    assert len(answer.split(".")[1]) == places


def test_calculate_keeps_a_whole_result_whole():
    """Verify that calculate keeps a whole result whole."""
    assert calculator._calculate("10 / 2") == "5"


def test_calculate_keeps_a_negative_result_negative():
    """Verify that calculate keeps a negative result negative."""
    assert calculator._calculate("2 - 5") == "-3"


def test_calculate_does_not_turn_a_huge_whole_float_into_an_integer():
    """Verify that calculate does not turn a huge whole float into an integer."""
    assert calculator._calculate("1e17") == "1e+17"


def test_calculate_accepts_the_expression_with_whitespace_around_it():
    """Verify that calculate accepts the expression with whitespace around it."""
    assert calculator._calculate("  7 * 6  ") == "42"


def test_calculate_names_the_expression_when_the_syntax_is_broken():
    """Verify that calculate names the expression when the syntax is broken."""
    with pytest.raises(ValueError) as error:
        calculator._calculate("2 +")

    assert "'2 +'" in str(error.value)


def test_calculate_names_the_expression_when_the_arithmetic_fails():
    """Verify that calculate names the expression when the arithmetic fails."""
    with pytest.raises(ValueError) as error:
        calculator._calculate("10 / 0")

    message = str(error.value)
    assert "'10 / 0'" in message
    assert "zero" in message


def test_calculate_names_the_expression_when_it_is_not_arithmetic_at_all():
    """Verify that calculate names the expression when it is not arithmetic at all."""
    with pytest.raises(ValueError) as error:
        calculator._calculate("Calculate 1200 times 2.68 for me")

    assert repr("Calculate 1200 times 2.68 for me") in str(error.value)


def test_calculate_refuses_an_expression_that_is_a_statement():
    """Verify that calculate refuses an expression that is a statement."""
    with pytest.raises(ValueError) as error:
        calculator._calculate("x = 2 + 2")

    assert "'x = 2 + 2'" in str(error.value)


def test_calculate_refuses_more_than_one_expression():
    """Verify that calculate refuses more than one expression."""
    with pytest.raises(ValueError):
        calculator._calculate("2 + 2; __import__('os')")


@pytest.mark.parametrize("expression", ["", "   ", None])
def test_calculate_rejects_an_empty_expression_before_parsing(expression):
    """Verify that calculate rejects an empty expression before parsing."""
    with pytest.raises(ValueError) as error:
        calculator._calculate(expression)

    assert repr(expression) in str(error.value)


def test_get_calculator_tools_returns_one_langchain_tool():
    """Verify that get calculator tools returns one langchain tool."""
    tools = calculator.get_calculator_tools()

    assert [type(tool) for tool in tools] == [Tool]
    assert [tool.name for tool in tools] == ["calculator"]


def test_get_calculator_tools_describes_the_tool_for_the_agent():
    """Verify that get calculator tools describes the tool for the agent."""
    tool = calculator.get_calculator_tools()[0]

    assert tool.description == calculator.CALCULATOR_DESCRIPTION


def test_the_description_tells_the_agent_what_it_may_write():
    """Verify that the description tells the agent what it may write."""
    description = calculator.CALCULATOR_DESCRIPTION

    assert all(name in description for name in calculator.CALCULATOR_FUNCTIONS)


def test_get_calculator_tools_entry_is_backed_by_the_calculation():
    """Verify that get calculator tools entry is backed by the calculation."""
    tool = calculator.get_calculator_tools()[0]

    assert tool.func("(1200 * 2.68) / 1000") == "3.216"


def test_get_calculator_tools_builds_a_fresh_tool_each_time():
    """Verify that get calculator tools builds a fresh tool each time."""
    assert (
        calculator.get_calculator_tools()[0] is not calculator.get_calculator_tools()[0]
    )
