"""Explicitly injected model answers; not provider quality evidence."""


def response(request, choices=None, nouls=None):
    """Build one wire-shaped answer set for every question in ``request``.

    ``choices`` lists the selected label per Choice question in request order.
    ``nouls`` maps Noul question names to probabilities; unnamed Noul questions
    default to 0.95 (clearly *not* drift) so a test must opt into drift.
    """

    answers = {}
    choice_index = 0
    for name, question in request["questions"].items():
        if question["type"] == "noul":
            value = 0.95 if nouls is None else nouls.get(name, 0.95)
            answers[name] = {"type": "noul", "noul": float(value)}
            continue
        labels = list(question["criteria"])
        selected = choices[choice_index] if choices else labels[0]
        choice_index += 1
        answers[name] = {
            "type": "choice",
            "choice": selected,
            "confidence": 1.0,
            "probabilities": {label: float(label == selected) for label in labels},
        }
    return {"model": request["model"], "answers": answers}


DRIFT_NOULS = {"behavior_change": 0.05, "serves_acceptance": 0.04, "evidence_increment": 0.1}
