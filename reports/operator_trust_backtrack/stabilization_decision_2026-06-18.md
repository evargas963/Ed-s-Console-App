# Stabilization decision

stabilization_gate_pass: True
card_explainability_gate_unblocked: True
safe_to_proceed_card_explainability: False

## Blocking (RTH proof still required)
- LIVE_GUEST_SLA_NOT_PROVEN
- DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN
- BASE_CAPTURE_NORMALIZATION_RTH_PROOF_NOT_COMPLETE
- RTH_VALIDATION_NOT_EXECUTED_AFTER_TRANSPORT_FIXES

## Recommended next branch
fix/ci-nonblocking-failures-triage
