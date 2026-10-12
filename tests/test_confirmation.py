import pytest

from app.confirmation import code_matches, interpret, spoken_digits


@pytest.mark.parametrize("utterance", ["Yes", "yeah go ahead", "Yep, do it.", "Confirmed", "correct", "Okay, please do"])
def test_affirmations(utterance):
    assert interpret(utterance) == "affirmed"


@pytest.mark.parametrize("utterance", ["No", "no thanks", "Don't do that", "Yes— wait, hold on", "cancel it",
                                       "I'm not sure", "Yes. No. Stop."])
def test_any_negation_wins(utterance):
    assert interpret(utterance) == "declined"


@pytest.mark.parametrize("utterance", ["Hmm", "what was that?", "the blue one", ""])
def test_ambiguous_is_unclear(utterance):
    assert interpret(utterance) == "unclear"


@pytest.mark.parametrize("utterance,digits", [
    ("yes one zero four two", "1042"),
    ("Yes, 1042", "1042"),
    ("yes 10 42", "1042"),
    ("yes, one oh four two", "1042"),
])
def test_spoken_digits(utterance, digits):
    assert spoken_digits(utterance) == digits


def test_code_matching():
    assert code_matches("yes one zero four two", "1042")
    assert not code_matches("yes one zero four three", "1042")
    assert not code_matches("yes", "1042")
