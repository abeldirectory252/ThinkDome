# Dynamic UI framework

ThinkDome UI is a server-compiled application shell. Applications declare
resources; users receive an effective manifest compiled for their identity.
The browser is a renderer, not a policy engine.

## Resource model

The public contract is intentionally small:

- `workspace`: navigational product area and its menu tree
- `page`: routable screen with a component layout
- `menu item`: a link, resource, report, URL, or nested group
- `component`: a whitelisted render primitive or layout container

Every resource may declare `allowed_roles`. The legacy `roles` key is accepted
for compatibility, but new configurations should use `allowed_roles`.

## Compilation pipeline

`UIManager.get_effective_ui(identity)` is the single compilation boundary:

1. Load developer-owned declarations.
2. Apply active administrator overrides.
3. Evaluate role policy and recursively remove unauthorized menu branches.
4. Apply user preferences such as hidden items and ordering.
5. Cache the resulting immutable-by-convention manifest by user and roles.

Raw CRUD methods are for trusted framework code and builder operations. Runtime
API reads use the compiled boundary, so a client cannot request a hidden page
or workspace by guessing its name.

## Ownership and change management

Developer declarations are synchronized idempotently and remain the source of
default structure. Administrator changes are stored as overlays, so a code
deployment does not erase visual/business customizations. Drafts are previewed
before publication and publication creates an audit entry and version record.

ThinkDome ships a bootstrap manifest in `thinkdome/config/ui/bootstrap.json`. It seeds
the initial administrator/developer pages through `UIManager` during startup;
it is not a browser fallback. Consequently, a fresh installation has a useful
pre-cooked UI, while an explicitly empty or removed manifest still renders
nothing.

The next extension points should preserve these boundaries: add a policy
resolver for attribute or tenant checks, add component schemas to the registry,
and add a transactional repository for multi-resource publishes. Avoid putting
authorization logic in browser templates or individual component renderers.
