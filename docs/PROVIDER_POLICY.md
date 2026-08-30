# Provider policy — provider-routing-v1

- Requests contain one exact configured `:free` model slug; model arrays, routers, aliases,
  `latest` endpoints and automatic model substitution are prohibited.
- Live preflight requires exact catalogue identity, zero prompt and completion prices,
  text input/output, advertised seed support and at least 16,384 context tokens.
- Requests use documented OpenRouter preferences `require_parameters=true` and
  `allow_fallbacks=false`.
- No named provider is pinned because a stable routing slug that preserves free access has
  not been qualified for both endpoints. Requested/resolved model and provider are stored.
- A resolved-model mismatch is rejected. Provider changes remain observed responses but
  trigger a documented protocol deviation and provider-stratified sensitivity report.
- Hidden reasoning is never substituted for assistant response text.
- Generation-v4 requests model-native reasoning with `reasoning.exclude=true`. The exclusion
  suppresses returned reasoning traces; it does not claim that reasoning is disabled. Reported
  reasoning-token usage and safe presence/length metadata are technical telemetry only.
- OpenRouter currently prefers `max_completion_tokens` and retains `max_tokens` as a documented
  compatibility field. Generation-v4 freezes `max_tokens` because candidate catalogue entries
  must advertise that or a semantically equivalent completion-limit field, and the exact
  calibrated free endpoint advertises `max_tokens`. The configured field is recorded per request.
