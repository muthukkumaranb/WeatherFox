def compute_severity(root_cause: str, residual: float, confidence: float) -> str:
    if residual is None:
        residual = 0.0
    severity_score = min(100, int(abs(residual) * confidence * 10))
    if severity_score >= 70:
        return "high"
    elif severity_score >= 40:
        return "medium"
    return "low"
