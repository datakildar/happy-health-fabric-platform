# Quality semantic model (Direct Lake)

`HappyQuality` is a Direct Lake model on `lh_gold_quality`, published by the data team and certified by the Power BI Center of Excellence after go-live.

| File | Contents |
|---|---|
| `measures.tmdl` | DAX measures on factMeasureSummary and factMeasureResult |
| `roles.tmdl` | Row- and object-level security roles |
| `relationships.md` | Relationships and why they run one way |

The Department leaders role uses a small `userHospital` table (user → hospital, from HR via Entra ID) loaded into the model.

**Security design** (docs/security.md):
* **Fixed identity for Direct Lake.** The model reads the lakehouse as the workspace identity, so report users need no lakehouse access and can't go around the model through OneLake or the SQL endpoint.
* Roles are enforced only for viewers. Workspace Admin, Member and Contributor roles bypass them, so business users get the model through a Power BI app, never a workspace role.
* No two-way relationships: OneLake security and Direct Lake both handle them badly, and they make row-level security hard to reason about.

The `.tmdl` files are excerpts in TMDL syntax to paste into the model's definition (Tabular Editor or Power BI Desktop developer mode); validate them in the tool before deploying.
