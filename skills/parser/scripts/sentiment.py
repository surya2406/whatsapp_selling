"""
Sentiment Classifier — pure keyword-based, no LLM.
Classifies conversation sentiment as positive, negative, or neutral.
"""

POSITIVE_KEYWORDS = {
    "thanks", "thank you", "great", "awesome", "love", "loved", "excellent",
    "good", "perfect", "amazing", "fantastic", "happy", "pleased", "wonderful",
    "nice", "super", "brilliant", "helpful", "best", "appreciate", "satisfied",
}

NEGATIVE_KEYWORDS = {
    "bad", "terrible", "awful", "horrible", "worst", "disappointed", "disgusted",
    "angry", "frustrated", "upset", "unhappy", "not working", "broken", "damaged",
    "refund", "return", "complaint", "problem", "issue", "wrong", "incorrect",
    "never", "useless", "waste", "scam", "fake", "cheated", "poor quality",
    "not satisfied", "dissatisfied", "hate", "dislike", "pathetic",
}


def classify_sentiment(messages: list[str]) -> str:
    """
    Input: list of message texts (last N messages from customer).
    Output: 'positive' | 'negative' | 'neutral'

    Strategy: count keyword hits in both lists. Negative wins ties to be safe
    (avoids sending offers to frustrated customers).
    """
    if not messages:
        return "neutral"

    combined = " ".join(messages).lower()
    words = set(combined.split())

    positive_hits = len(words.intersection(POSITIVE_KEYWORDS))
    negative_hits = len(words.intersection(NEGATIVE_KEYWORDS))

    # Also check multi-word phrases
    for phrase in NEGATIVE_KEYWORDS:
        if " " in phrase and phrase in combined:
            negative_hits += 2  # Weight phrases higher

    for phrase in POSITIVE_KEYWORDS:
        if " " in phrase and phrase in combined:
            positive_hits += 1

    if negative_hits > 0:
        return "negative"
    elif positive_hits > 0:
        return "positive"
    else:
        return "neutral"
