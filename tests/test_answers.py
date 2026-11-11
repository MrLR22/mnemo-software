# tests/test_answers.py: typing slips must not send a question down the wrong answering route.
import services  # noqa: F401
from services.api.answers import tidy_question

DIARY = {"fridge", "glass", "tap", "kettle", "drawer", "measuring", "cup"}


def test_typos_in_the_words_that_matter_are_fixed():
    assert tidy_question("did i close my fridgeg", DIARY) == "did i close my fridge"
    assert tidy_question("Did i turn of the tap", DIARY) == "Did i turn off the tap"
    assert tidy_question("How many tmes did i pick my glass", DIARY) == "How many times did i pick my glass"


def test_correct_questions_are_left_alone():
    for q in ("Did I close the drawer?", "what did i do after lunch", "Where did I put the measuring cup?"):
        assert tidy_question(q, DIARY) == q
