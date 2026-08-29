# Development decision log

## 29 August 2026 — pre-study-readiness preservation

- Legacy integration checkpoint: `e53f07b240adfd6d6b90a5e0d41d5a33ac882123`.
- Preservation tag: `pre-study-readiness-v2-20260829` (same target and annotation as the
  retired tool-prefixed tag).
- Baseline validation: 93 tests passed; Ruff lint passed; compilation passed; Pilot V3
  offline preflight made zero network calls. Ruff format check identified 14 pre-existing
  formatting/line-ending differences.
- Fingerprint algorithm: SHA-256 over sorted repository-relative path, NUL, file bytes, NUL.
- Pilot V1: 25 files, `f1c3a050c306d69cff0fea7dc9ca03fe1b7f8bd0e3d6fccb3e7d49661b4f2496`.
- Pilot V2: 22 files, `e08b1a247662cc8a5c60e60e84086974cd2d4742c21118c92dea5b2b1beabda0`.
- Pilot V3: 26 files, `dab2e3aafe0a65273aeec9e174ff089181c59db28c80b8673c3f8467042d3952`.
- Endpoint screen: one result file, `dae8db55367fc1f8f8c92e1ec231801ef5f58f6d89fb221aed8f867edc81837b`.
- Scenarios: nine files, `8c730208b66f08bc9f1a71911b3895cb14202280f412a7a4b96667fc288147b6`.
- Histories: three files, `895748698d6faaffcedda72e740ff5b50f8de8ba4a3701550bd3d3d06ade4ee9`.
- Draft rubric: one file, `c371afadebf59f6ae0f51f62564bedbda534e510deff3ef8c333dc3bc3f91a41`.
- Pre-revision active manifest: `4112263355db4e9a67653ce729ca312cae2bdf4bdd0031f1387a641626f2136a`.
- Pre-revision model configuration: `20a4617c6e1dec32196b534f55d4efb4681225ed337b7b1407b180738b5364f2`.

## Study V2 decision

The 108-conversation Study V1 design is retained in Git history and the deviation record.
Study V2 adopts two technically plausible endpoints and 72 conversations before any main
data exist. The main study remains blocked by academic approval, endpoint qualification and
annotation readiness.

Post-revision planned-material fingerprints are manifest
`007bfad402054ceabcfecc599e935cf5ccafa8e907c5cae9df9bffaa80c56865` and model
configuration `2946035280ef3468aee853e4a348c92c8df11f37516723843bd3f45cab6bfea4`.
The archived Pilot V3 model configuration matches the pre-revision file byte-for-byte after
normalising line endings. Scenarios, histories, rubric and all four technical-evidence
fingerprints are unchanged.

## 29 August 2026 — Pilot V4 outcome and prospective generation-v3 correction

Pilot V4 (`technical-pilot-v4.0.0`) completed four conversations and 24/24 technical
response slots under archived configuration 2.0.0 / generation-v2 / 512 maximum completion
tokens. It used 24/32 HTTP attempts with no technical errors or model mismatches. The frozen
assessor returned `FAIL` with source-evidence hash
`36ba9906eed1628c95f50f18d4c149007bec7f04eac399c55c5599d5a858fb3e`.

Safe private-record cross-tab:

| Requested model | Resolved model | Provider | Finish reason | Truncated | Responses |
|---|---|---|---|---:|---:|
| `minimax/minimax-m3:free` | `minimax/minimax-m3:free` | GMICloud | `stop` | false | 12 |
| `nvidia/nemotron-3-super-120b-a12b:free` | `nvidia/nemotron-3-super-120b-a12b:free` | Nvidia | `length` | true | 12 |

Because successful turns are immutable and no response slots are missing, the eight remaining
attempts cannot replace the 12 truncated observations. Pilot V4 cannot become PASS through
resume and is closed as failed technical evidence. No response or prompt content was used in
this audit output.

No main-study data exist. Configuration 2.1.0 / generation-v3 prospectively changes only the
maximum completion tokens from 512 to 1024. Pilot V5 (`technical-pilot-v5.0.0`) uses a new
raw and qualification namespace and must independently PASS before Study V2 can construct a
live provider. This software gate does not establish supervisor, ethics or rubric approval.
