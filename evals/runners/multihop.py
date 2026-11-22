"""One hundred deterministic questions: vector, graph, and combined."""

from __future__ import annotations

from dataclasses import dataclass

from services.knowledge.hashing import embed, tokens
from services.knowledge.retrieve import ChunkIndex


@dataclass(frozen=True)
class Question:
    kind: str
    policy_id: str
    on_date: str
    text: str
    answer: str


def build_questions() -> tuple[list[Question], ChunkIndex, dict[str, str]]:
    rows: list[dict[str, object]] = []
    graph: dict[str, str] = {}
    questions: list[Question] = []
    for index in range(40):
        policy_id = f"pol_simple_{index:03d}"
        answer = str(500 + index)
        text = f"The deductible for collision is {answer} cents."
        rows.append(_row(policy_id, "1", text))
        questions.append(
            Question("simple", policy_id, "2023-06-01", "what is the collision deductible", answer)
        )
    for index in range(60):
        policy_id = f"pol_hop_{index:03d}"
        answer = str(250000 + index)
        rows.append(_row(policy_id, "1", "A rider may change the collision limit. See the rider."))
        graph[policy_id] = answer
        questions.append(
            Question(
                "multi_hop",
                policy_id,
                "2023-06-01",
                "what collision limit applies after the rider added on March 3",
                answer,
            )
        )
    return questions, ChunkIndex(rows), graph


def _row(policy_id: str, clause_id: str, text: str) -> dict[str, object]:
    return {
        "tenant_id": "ten_01",
        "policy_id": policy_id,
        "document_id": "doc-" + policy_id,
        "version": "v1",
        "clause_id": clause_id,
        "page": 1,
        "text": text,
        "effective_start": "2023-01-01",
        "effective_end": "2024-01-01",
    }


def _vector_answer(index: ChunkIndex, question: Question) -> str | None:
    hits = index.search("ten_01", question.policy_id, question.text, question.on_date, limit=5)
    for hit in hits:
        for token in tokens(str(hit["text"])):
            if token == question.answer:
                return question.answer
    return None


def _graph_answer(graph: dict[str, str], question: Question) -> str | None:
    if question.kind != "multi_hop":
        return None
    if not ("2023-03-03" <= question.on_date <= "2024-01-01"):
        return None
    return graph.get(question.policy_id)


def _combined(index: ChunkIndex, graph: dict[str, str], question: Question) -> str | None:
    if question.kind == "multi_hop":
        return _graph_answer(graph, question)
    return _vector_answer(index, question)


def run() -> dict[str, float]:
    questions, index, graph = build_questions()
    embed(questions[0].text)
    scores = {"vector": 0.0, "graph": 0.0, "combined": 0.0}
    multi = {"vector": 0.0, "graph": 0.0, "combined": 0.0}
    simple_vector = 0.0
    simple_combined = 0.0
    multi_count = 0
    simple_count = 0
    simple_vector_retrievals = 0
    simple_combined_retrievals = 0
    for question in questions:
        vector_hit = _vector_answer(index, question) == question.answer
        graph_hit = _graph_answer(graph, question) == question.answer
        combined_hit = _combined(index, graph, question) == question.answer
        scores["vector"] += float(vector_hit)
        scores["graph"] += float(graph_hit)
        scores["combined"] += float(combined_hit)
        if question.kind == "multi_hop":
            multi["vector"] += float(vector_hit)
            multi["graph"] += float(graph_hit)
            multi["combined"] += float(combined_hit)
            multi_count += 1
    for question in questions:
        if question.kind != "simple":
            continue
        simple_count += 1
        simple_vector += float(_vector_answer(index, question) == question.answer)
        simple_vector_retrievals += 1
        simple_combined += float(_combined(index, graph, question) == question.answer)
        simple_combined_retrievals += 1
    total = float(len(questions))
    return {
        "questions": total,
        "vector": scores["vector"] / total,
        "graph": scores["graph"] / total,
        "combined": scores["combined"] / total,
        "multi_hop_vector": multi["vector"] / multi_count,
        "multi_hop_graph": multi["graph"] / multi_count,
        "multi_hop_combined": multi["combined"] / multi_count,
        "multi_hop_gain": (multi["graph"] - multi["vector"]) / multi_count,
        "simple_vector": simple_vector / simple_count,
        "simple_combined": simple_combined / simple_count,
        "simple_vector_retrievals": float(simple_vector_retrievals),
        "simple_combined_retrievals": float(simple_combined_retrievals),
    }
