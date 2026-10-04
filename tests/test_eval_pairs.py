"""scripts/eval_pairs.py: оценка ответов судьи по эталону на фейковых данных (кэш наполняется фейковым transport, без сети)."""
import json
import os
import sys
from pathlib import Path

import pytest

from src.config import load_config
from src.llm import GeminiPairJudge, LlmClient
from src.llm.cache import LlmCache
from src.pipeline import run_pipeline
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import eval_pairs as ep  # noqa: E402
import verify_matching as vm  # noqa: E402

CFG = load_config()


def rec(a_row, b_row, raw=None, result=None, a_name="A", b_name="B"):
    return {"a": {"file": "act.xlsx", "row": a_row, "name_raw": a_name}, "b": {"file": "vor.xlsx", "row": b_row, "name_raw": b_name},
            "raw": raw, "result": result}


def ans(same, conf=0.9, reason="r"):
    return {"same_work": same, "confidence": conf, "reason": reason}


def test_confusion_matrix_and_diffs_on_fake_records():
    truth = {("act.xlsx", 1): "i1", ("vor.xlsx", 1): "i1", ("act.xlsx", 2): "i2", ("vor.xlsx", 2): "i2", ("act.xlsx", 3): "i3",
             ("vor.xlsx", 3): "i9"}
    records = [rec(1, 1, ans(True)),                    # верно «одна»
               rec(3, 3, ans(False)),                   # верно «разные»
               rec(3, 3, ans(True), a_name="X"),        # ложное «одна»
               rec(2, 2, ans(False)),                   # пропущенное «одна»
               rec(2, 2, None)]                         # нет ответа
    m = ep.confusion(records, truth)
    assert (m["tp"], m["tn"], m["fp"], m["fn"], m["unanswered"], m["answered"]) == (1, 1, 1, 1, 1, 4)
    assert m["accuracy"] == 0.5
    assert {d["kind"] for d in m["diffs"]} == {"ложное «одна работа»", "пропущенное «одна работа»"}


def test_outcome_classes():
    assert ep.outcome(rec(1, 1, None)) == "no_answer"
    assert ep.outcome(rec(1, 1, ans(True), None)) == "low_confidence"
    assert ep.outcome(rec(1, 1, ans(True), {"same_work": False, "confidence": 0.9, "reason": f"{ep.CHECK_PREFIX}: d12 и d8"})) == "rejected_by_check"
    assert ep.outcome(rec(1, 1, ans(True), ans(True))) == "answered"


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic_eval")
    gen.generate(out_dir=out, meta_dir=out)
    return out


class SeedingJudge:
    """Наполняет кэш через настоящий GeminiPairJudge: ответы фейкового transport берутся из эталона.
    flip_first=True: ответ на первую пару нарочно неверный. Кэш только во временной папке (LLM_CACHE_DIR из conftest)."""
    available = True

    def __init__(self, truth, flip_first=False):
        self.truth, self.flip_first, self.state = truth, flip_first, {}
        cache_dir = Path(os.environ["LLM_CACHE_DIR"])
        assert ROOT not in cache_dir.parents, "тест не должен трогать кэш репозитория"
        llm = {**CFG["rules"]["llm"], "call_pause_seconds": 0}
        client = LlmClient(llm, transport=self._transport, cache=LlmCache(cache_dir), sleep=lambda s: None, env={})
        self.inner = GeminiPairJudge(client, CFG)

    def _transport(self, prompt, schema):
        return json.dumps(self.state["answer"])

    def judge_pair(self, a, b, context):
        same = self.truth.get((a["file"], a["row"])) == self.truth.get((b["file"], b["row"]))
        if self.flip_first:
            same, self.flip_first = not same, False
        self.state["answer"] = {"same_work": same, "confidence": 0.95, "reason": "по эталону (тест)"}
        return self.inner.judge_pair(a, b, context)


def seed_cache(synth, tmp_path, flip_first=False):
    judge = SeedingJudge(vm.load_truth(), flip_first)
    run_pipeline(synth, tmp_path / "seed.db", "llm", judge=judge, cfg=CFG, auto_ai=False)
    return judge


def test_analyze_from_cache_makes_no_api_calls_and_finds_everything_with_truthful_answers(synth, tmp_path):
    seed_cache(synth, tmp_path)
    a = ep.analyze(str(synth), CFG)
    c = a["confusion"]
    assert a["stats"]["calls"] == 0 and c["unanswered"] == 0 and c["answered"] == len(a["records"]) > 0
    assert c["fp"] == c["fn"] == 0 and c["accuracy"] == 1.0
    assert a["real"]["found"] >= a["base"]["found"] and a["ceiling"]["found"] == 12
    assert a["outcomes"]["no_answer"] == 0
    # проверка кода отклоняет «одна работа» там, где у строки акта kind по умолчанию work, а в ВОР material (известная причина, см. отчёт)
    assert a["checks"]["rejected"] == a["checks"]["by_kind"].get("kind", 0)


def test_analyze_reports_unanswered_pairs_without_api_calls(synth, tmp_path):
    judge = seed_cache(synth, tmp_path)
    next(iter(sorted(judge.inner.client.cache.dir.glob("[!_]*.json")))).unlink()     # одной пары нет в кэше
    a = ep.analyze(str(synth), CFG)
    assert a["confusion"]["unanswered"] >= 1 and a["outcomes"]["no_answer"] >= 1
    assert a["stats"]["calls"] == 0                         # без кэша API всё равно не вызывается


def test_analyze_detects_model_error_against_truth(synth, tmp_path):
    seed_cache(synth, tmp_path, flip_first=True)
    a = ep.analyze(str(synth), CFG)
    assert a["confusion"]["fp"] + a["confusion"]["fn"] >= 1 and a["confusion"]["diffs"]
    assert a["confusion"]["accuracy"] < 1.0
