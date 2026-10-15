# Bayti

Ijara (Ijara Muntahia Bittamleek, lease ending with ownership) financing workflow with document control.

Pure Python 3.10+, no dependencies.

```
python -m unittest discover -s tests -t .   # run tests
python -m bayti.ijara demo                  # run one application through every stage
python -m bayti.ijara docs                  # regenerate docs/ijara-workflow.md
python -m bayti.ijara docs --check          # CI check that the docs are current
```

## What it does

- Moves an application through 11 stages, from application to title transfer (see [docs/ijara-workflow.md](docs/ijara-workflow.md)).
- Each stage lists its required documents. A stage cannot be left until each one is uploaded or generated, then verified.
- Maker-checker and role authority apply to document verification and stage approvals.
- Bank-issued documents (offer, promise to lease, Ijara agreement, promise to transfer, rental schedule, delivery certificate, transfer deed) are generated from templates in `bayti/ijara/templates/`.
- Files are stored with a SHA-256 hash, versioned on re-upload, and every action is written to an audit log.
- The workflow documentation is generated from the same definition the engine enforces, and a test fails if the committed copy is stale.

## Before production use

- The templates are drafts. Legal and the Shariah Supervisory Board must approve the wording.
- `Policy` defaults (50% rental-to-income, price at most 100% of valuation) are placeholders. Set them from approved credit policy.
- State is held in memory and files in a local folder. Persistence, authentication, and integration with core banking, KYC and e-signature are not included.
- The stage list and required documents reflect a typical retail Ijara. Adjust `bayti/ijara/definition.py` to the bank's approved product programme.
