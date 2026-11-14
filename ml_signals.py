"""Illustrative ML, trained on synthetic examples; no accuracy claims."""
from functools import lru_cache
SCAM = ['Your refund is ready enter your UPI PIN to receive it', 'Scan QR enter pin to receive cashback immediately', 'Urgent update KYC or your account will be blocked', 'Your bank account blocked verify account now', 'You won a lottery pay processing fee to claim prize', 'Share your OTP with customer support for verification', 'Install AnyDesk share screen to get refund', 'Send money first to release cashback reward', 'Act now reward expires within 5 minutes', 'Tell me password and OTP to activate account', 'Pay registration fee to receive lottery winnings', 'Customer care asks remote access to fix payment', 'Refund pending scan payment code enter your pin', 'Electricity account will be blocked immediately pay now', 'Bank officer asks share pin for account verification', 'Transfer money to unlock your prize']
NORMAL = ['Please pay 500 for your order at Sample Store', 'Lunch cost 250 here is my UPI address', 'Invoice attached please confirm amount', 'Refund will arrive in original bank account', 'Payment received thank you for shopping', 'Check order details in official app', 'Please send rent to usual landlord account', 'I bought groceries need to pay the shop', 'Package delivered today thank you', 'We will never ask for pin or OTP', 'Pay your share of dinner when convenient', 'Store name and amount match my bill', 'Buying a book at the counter', 'Cashback credited no action required', 'Check recipient before sending payment', 'Receipt for completed purchase']
@lru_cache(maxsize=1)
def model():
    try:
        from sklearn.pipeline import make_pipeline
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        return None
    pipeline = make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), LogisticRegression(C=4, random_state=42))
    pipeline.fit(SCAM + NORMAL, [1] * len(SCAM) + [0] * len(NORMAL))
    return pipeline
def predict_signal(text):
    classifier = model()
    result = dict(available=classifier is not None, training='32 synthetic illustrative examples; no validated production accuracy', model='TF-IDF + logistic regression', label='unavailable', model_score=None)
    if classifier is not None and text.strip():
        value = float(classifier.predict_proba([text])[0][1])
        result.update(label='scam-pattern' if value >= .5 else 'ordinary-pattern', model_score=round(value, 3))
    elif classifier is not None:
        result['label'] = 'insufficient-text'
    return result
