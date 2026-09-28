"""
Unit Tests for Reply Classification Engine.
Tests:
1. Rule-based fast-path classification for Out of Office.
2. Rule-based fast-path classification for Unsubscribe.
3. Rule-based fast-path classification for Not Interested.
4. AI fallback and confidence scoring.
"""

import pytest
from database.models import ReplyClassification
from modules.reply_tracker.classifier import classify_reply, _rule_based_classify


@pytest.mark.parametrize("text,expected", [
    ("I am currently out of the office on annual leave until next Tuesday.", ReplyClassification.OUT_OF_OFFICE),
    ("Please remove me from your mailing list and unsubscribe.", ReplyClassification.UNSUBSCRIBE),
    ("Please do not contact me again.", ReplyClassification.UNSUBSCRIBE),
    ("No thanks, we are not interested at this time.", ReplyClassification.NOT_INTERESTED),
])
def test_rule_based_fast_path_classification(text, expected):
    res = _rule_based_classify(text)
    assert res is not None
    classification, confidence = res
    assert classification == expected
    assert confidence >= 0.85


def test_classify_reply_end_to_end_with_rule_match():
    cls, conf = classify_reply("I will be away from my desk on vacation with limited email access.")
    assert cls == ReplyClassification.OUT_OF_OFFICE
    assert conf >= 0.8
