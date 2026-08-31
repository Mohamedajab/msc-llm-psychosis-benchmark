# Data management

Status: Confirmed for Study V2 collection.

## Storage and integrity

Main-study raw responses are stored in the project's private raw-data structure. Successful
responses are append-only evidence and are not edited after collection. Job state and private
blinding maps are kept separately from public project material. API keys and other credentials
are local environment settings and must not be tracked by Git.

Annotation exports and analysis files are derived from the preserved raw evidence. Derived
files must retain identifiers or hashes that allow them to be reconciled with their source
records without exposing private mappings.

## Backup and retention

During collection and analysis, the private project data should be backed up to an access-
controlled location separate from the working copy. Backups should preserve the append-only
raw records and the configuration needed to interpret them. Raw evidence and necessary derived
records should be retained until the dissertation has been assessed and any university retention
requirements have been checked. Deletion after that point should include private backups and
local credentials where they are no longer needed.

## Access and release

Access to raw responses, private job state, blinding maps and unredacted annotation notes is
limited to the student and any authorised academic reviewer. Public releases may include code,
frozen non-sensitive configuration, aggregate results and suitably reviewed derived material.
They must not include credentials, private maps, raw provider payloads or material whose release
has not been checked for sensitive content and provider terms.

The benchmark uses synthetic inputs and model-generated responses. It does not use patient,
participant or clinical-record data. This record describes the project's practical arrangements;
it does not claim a separate institutional data-management approval.
