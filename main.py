import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.request import urlopen
from urllib.error import URLError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from fraud_engine import analyze_message, finalize_assessment
from dotenv import load_dotenv
from llm_review import analyze_context, ModelResponseError, OLLAMA_TIMEOUT_SECONDS

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
DB = ROOT / 'data' / 'scamsense.db'
app = FastAPI(title='ScamSense', version='2.0.0', description='Context-aware payment review • Team supercode')
logger = logging.getLogger('scamsense.llm')

@contextmanager
def database():
    DB.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, created_at TEXT, result TEXT, feedback TEXT)')
            yield connection
    finally:
        connection.close()

class AnalysisRequest(BaseModel):
    message: str = Field(default='', max_length=12000)
    qr_data: str = Field(default='', max_length=4000)
    context: str = Field(default='', max_length=4000)
    intent: Literal['send', 'receive', 'unsure'] = 'unsure'
    expected_payee: str = Field(default='', max_length=200)
    expected_amount: float | None = Field(default=None, gt=0, le=100000000, allow_inf_nan=False)
    save_review: bool = False
    use_llm: bool = Field(default_factory=lambda: bool(os.getenv('SCAMSENSE_OLLAMA_MODEL')))

    @model_validator(mode='after')
    def has_input(self):
        if not any(value.strip() for value in [self.message, self.qr_data, self.context]):
            raise ValueError('Add a message, caller context or QR payload first.')
        return self

class FeedbackRequest(BaseModel):
    label: Literal['suspected_scam', 'legitimate', 'unsure']
    useful: bool

def explain_with_local_llm(result, values):
    model = os.getenv('SCAMSENSE_OLLAMA_MODEL')
    if not model:
        result['llm_status'] = 'Not configured; using evidence template.'
        return
    original_assessment = result.copy()
    try:
        analysis = analyze_context(values, 'ollama', model, timeout=OLLAMA_TIMEOUT_SECONDS)
        if not analysis['evidence_grounded']:
            raise ModelResponseError('evidence_validation')
        critical_rule = any(item.get('severity') == 'HIGH' for item in result.get('evidence', []))
        if critical_rule and analysis['review']['risk'] != 'HIGH':
            raise ModelResponseError('risk_conflict')
        result['context_review'] = analysis['review']
        finalize_assessment(result)
        explanation = analysis['review']['explanation']
        if critical_rule:
            # Do not let free-form prose imply scanning alone causes a debit.
            # The critical action/amount warning comes from parsed payment facts.
            generic_warning = next((item['detail'] for item in result['evidence'] if item['code'] == 'generic_payee'), '')
            explanation = result['recommendation'] + (' ' + generic_warning if generic_warning else '')
            analysis['review']['explanation'] = explanation
        elif result['risk'] == 'HIGH':
            explanation = result['recommendation'] + '\n\n' + explanation
        result.update(context_review=analysis['review'], llm_duration_ms=analysis['latency_ms'],
                      explanation=explanation, explanation_source=f'Local Ollama / {model}' + (' + deterministic payment warning' if critical_rule else ''),
                      llm_status='Validated local context assessment merged into the final risk score.')
    except Exception as error:
        result.clear()
        result.update(original_assessment)
        if isinstance(error, TimeoutError) or (isinstance(error, URLError) and isinstance(error.reason, TimeoutError)):
            code, description = 'timeout', f'Local analysis timed out (timeout budget: {OLLAMA_TIMEOUT_SECONDS}s)'
        elif isinstance(error, ModelResponseError):
            code, description = error.code, f'Local analysis failed validation ({error.code})'
        elif isinstance(error, URLError):
            code, description = 'connection_error', 'Ollama could not be reached'
        else:
            code, description = 'provider_error', 'Local model request failed'
        # Never print the prompt, model response, provider body or credentials.
        logger.warning('Local model fallback: %s', code)
        result.pop('context_review', None)
        result['llm_error_code'] = code
        result['llm_status'] = description + '; deterministic evidence template used. High-severity rule floors remain active.'
        finalize_assessment(result)
        result['explanation_source'] = 'Evidence template'
        result['explanation'] = result.get('summary', '') + ' ' + result['recommendation']

@app.get('/health')
def health():
    model = os.getenv('SCAMSENSE_OLLAMA_MODEL')
    reachable = False
    available = False
    if model:
        try:
            with urlopen('http://127.0.0.1:11434/api/tags', timeout=2) as response:
                models = json.load(response).get('models', [])
            reachable = True
            available = any(item.get('name') == model for item in models)
        except Exception:
            pass
    return dict(status='ScamSense is running', version='2.0.0', llm_configured=bool(model),
                llm_model=model, ollama_reachable=reachable, llm_ready=available)

@app.post('/analyze')
def analyze(request: AnalysisRequest):
    start = time.perf_counter()
    values = request.model_dump(exclude={'save_review', 'use_llm'})
    result = analyze_message(**values)
    result.update(id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc).isoformat(), saved=request.save_review,
                  llm_status='Not requested; evidence template used.')
    if request.use_llm: explain_with_local_llm(result, values)
    finalize_assessment(result)
    result['duration_ms'] = round((time.perf_counter() - start) * 1000)
    if request.save_review:
        with database() as db:
            db.execute('INSERT INTO reviews VALUES (?, ?, ?, NULL)', (result['id'], result['created_at'], json.dumps(result)))
    return result

@app.get('/reviews')
def reviews():
    with database() as db:
        rows = db.execute('SELECT * FROM reviews ORDER BY created_at DESC LIMIT 100').fetchall()
    return [dict(**json.loads(row['result']), feedback=json.loads(row['feedback']) if row['feedback'] else None) for row in rows]

@app.post('/reviews/{review_id}/feedback')
def feedback(review_id: str, request: FeedbackRequest):
    with database() as db:
        cursor = db.execute('UPDATE reviews SET feedback=? WHERE id=?', (request.model_dump_json(), review_id))
        if not cursor.rowcount: raise HTTPException(404, 'Saved review not found.')
    return {'status': 'Feedback saved; labels are user reports, not verified outcomes.'}

@app.delete('/reviews')
def clear_reviews():
    with database() as db: db.execute('DELETE FROM reviews')
    return {'status': 'Saved reviews deleted'}

app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
