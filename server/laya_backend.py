"""Local multilingual Laya adapter; no network access during inference."""
import os
import threading

from routing_policy import TIERS, EFFORTS

_lock = threading.Lock()
_agent = None
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_default_laya_root = os.path.abspath(os.path.join(_repo_root, "..", "laya"))
MODEL_PATH = os.path.expanduser(
    os.environ.get(
        "LAYA_MODEL_PATH",
        os.path.join(
            os.environ.get("LAYA_ROOT", _default_laya_root),
            "models",
            "multilingual",
        ),
    )
)
POLICY_VERSION = "laya-local-v1"

_profiles = (
    "Simple direct lookup, translation, extraction or small edit",
    "Bounded multi-step professional analysis, coding and debugging",
    "Hard novel reasoning, interacting constraints, exhaustive proof or architecture",
)
_depths = (
    "minimal work: direct answer or single tool lookup",
    "a few reasoning steps with a quick check",
    "many reasoning steps with thorough verification",
    "extended search and comparison of many alternatives",
    "exhaustive difficult investigation with a very large reasoning budget",
)
_labels = {
    f"option_{i * len(EFFORTS) + j + 1}": f"{model}:{effort}"
    for i, model in enumerate(TIERS) for j, effort in enumerate(EFFORTS)
}
QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": (
            "Select the model and reasoning budget sufficient to complete and verify "
            "the user's entire task. Avoid unnecessary capacity on simple requests."
        ),
        "criteria": {
            label: f"{_profiles[i // len(EFFORTS)]}; {_depths[i % len(EFFORTS)]}"
            for i, label in enumerate(_labels)
        },
    },
}


def predict(state, questions=None):
    global _agent
    # Shared model and MPS execution are serialized across HTTP handler threads.
    with _lock:
        if _agent is None:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            import laya
            import torch
            torch.set_num_threads(4)
            _agent = laya.load(MODEL_PATH)
            _agent.cfg["head_max_len"] = 768
            _agent.cfg["max_len"] = 1536
        result = _agent.predict(state, QUESTIONS if questions is None else questions)
        if questions is None:
            answer = result["answers"]["route"]
            answer["choice"] = _labels[answer["choice"]]
            answer["probabilities"] = {
                _labels[label]: probability
                for label, probability in answer["probabilities"].items()
            }
        result["model"] = "laya-multilingual"
        return result
