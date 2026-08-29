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
