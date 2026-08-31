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
- Provider routing may therefore vary and is a possible implementation confound. Screening and
  Pilot V6 record whether an endpoint exposes one or multiple free providers. Provider counts
  are retained per response and described or stratified where variation occurs; exact model
  identity does not imply invariant backend infrastructure.
- Hidden reasoning is never substituted for assistant response text.
- Generation-v4 requests model-native reasoning with `reasoning.exclude=true`. The exclusion
  suppresses returned reasoning traces; it does not claim that reasoning is disabled. Reported
  reasoning-token usage and safe presence/length metadata are technical telemetry only.
- Generation-v4 freezes a provider-independent 4096-token completion envelope. For each exact
  model, retained catalogue evidence deterministically selects `max_completion_tokens` when it
  is advertised, otherwise `max_tokens`; absence of both is ineligible. The selected translation
  is frozen in screening/selection/model configuration, sent with `require_parameters=true`,
  stored in request parameters, and covered by the payload hash.
