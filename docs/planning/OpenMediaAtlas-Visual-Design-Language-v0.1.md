# OpenMediaAtlas: visual design language

Draft direction for review · 20 September 2026

**Aim:** an inviting cultural reference site with the density of a useful catalog. It should reward scanning and close reading. This is a design contract for the coding agent, not a rendered mockup or a tested component library.

## 1. Principles that constrain implementation

1. Work identity and connections lead; marketing copy does not occupy the first screen.
2. Related information sits together. Use adjacent columns for credits, metadata and rights when width permits.
3. Density comes from grouping and restrained spacing, not tiny fonts or hidden labels.
4. Use rows for comparable records and cards for items whose imagery matters. Do not wrap every field or section in a separate card.
5. Give the page one strongest visual action. Secondary actions are quiet, labeled controls.
6. Unknown data looks intentionally absent; empty panels should not dominate thin records.
7. Aesthetic polish must survive long titles, missing posters, conflicting data, and many credits.

## 2. Proposed visual character

Warm ivory background, white reading surfaces, dark ink text, a restrained plum accent, thin warm-gray rules. Slight editorial character in work titles; clear system sans for interface and metadata. The palette is provisional, not an assumption that OpenMediaAtlas must share the personal website's colors.

| Token | Starting value | Purpose |
|---|---|---|
| Page background | `#F7F5F0` | Warm neutral base |
| Surface | `#FFFFFF` | Forms/popovers and selected panels |
| Primary text | `#25232A` | Main reading color |
| Secondary text | `#62606A` | Metadata and helper text; verify contrast in context |
| Accent | `#614477` | Links, selection and one primary action |
| Divider | `#DCD7CE` | Subtle section boundaries, not sufficient alone for form controls |
| Control boundary | `#827C88` | Inputs where a visible boundary is required; verify actual contrast |
| Small radius | `4px` | Inputs, compact buttons and chips |
| Panel radius | `8px` | Popovers/dialogs, used sparingly |
| Spacing scale | `4, 8, 12, 16, 24, 32px` | Predictable rhythm |

Avoid decorative gradients, glass effects, floating metric tiles, excessive shadows, pill-shaped everything, and giant centered hero headings. These are starting design choices, not universal prohibitions on visual play.

## 3. Typography and control sizing

| Element | Desktop starting target |
|---|---|
| Work title | 28–34px, about 1.15 line height; optional Georgia/system serif |
| Page section title | 18–20px, semibold |
| Main prose | 16px, 1.5–1.6 line height; roughly 65–75 characters wide |
| Metadata / result secondary line | 14px, 1.4–1.5 line height |
| Small helper / badge | 12–13px, reserved for nonessential text |
| Standard button/input | About 36px visual height on desktop; adequate hit area and focus ring |
| Touch controls | Aim for 44px hit area; do not shrink mobile actions to preserve density |
| Table/result row | Content-driven, usually 40–56px without a cover; taller for wrapped text |

Support browser zoom and user font settings. These are starting targets, not fixed heights that clip translated labels. No information should require hover, color perception, or a perfect mouse pointer to access.

## 4. Desktop work page composition

At around 1440px viewport width, use a centered content region of about 1200–1280px with 24px outer gutters. Around 1100px and above, the main body can use approximately 2/3 content and 1/3 sidebar, separated by 24px. Switch based on content fit, not a device name.

| Zone | Composition |
|---|---|
| Global navigation | About 56px high, logo/name, useful search field, browse, account. No oversized branding block. |
| Work header | Cover/poster roughly 144–176px wide beside title, creator, form/year/language line, short summary and compact actions. Natural image aspect ratio. |
| Main content column | Local relationship strip/map; description; versions/releases; collection/episode contents; community sections as available. |
| Side column | Compact facts, principal/full-credit access, scoped rights summary, read/watch links, provenance/update controls. |
| Lower page | Lists and community details when useful. Secondary maintenance links do not compete with identity. |

The header should not consume an entire laptop screen. As a fixture test at 1440 × 900, the page should show the work identity, primary actions, several useful facts and the beginning of its relationship section without scrolling. Measure on both a rich and a sparse record; do not force every record into identical panel heights.

When the sidebar lacks content, let the page become simpler rather than showing “No data” in five boxes. A wide layout is allowed to have deliberate breathing room; fill it with relevant information, not filler widgets.

## 5. Relationship presentation

Default to a small neighborhood, not a family tree. Use a centered current-work card with directly related source/derived cards. Three to seven cards is a useful initial limit; “View all” opens a compact list. Several parents must remain possible.

- Each card: small cover or format fallback, title, year, form. Keep card widths roughly 160–220px when space allows.
- Label lines with verbs; source-to-derived display direction is consistent regardless of stored edge direction.
- Keep sequel, trailer and inspiration links in separate labeled rows when the main map would become noisy.
- Selected work is visually strongest; other nodes are not giant equal-weight tiles.
- Keyboard users can reach every node and open relationship evidence. Provide an equivalent textual relationship list.
- On mobile use stacked groups such as “Based on” and “Adaptations,” not a horizontally overflowing graph.

## 6. Dense components to standardize first

| Component | Specification |
|---|---|
| Result row | 48–64px-wide thumbnail, title/creator, short metadata line, optional connection badge, compact save control. Use list view by default; image grid optional. |
| Metadata block | Label/value grid with consistent label width; values wrap. No separate rounded card for each datum. |
| Credit row | Role, linked name, optional credited-as name/character; reveal more credits progressively. |
| Version group | Label, translator/cut, language/date, release count; expand inline. Standalone versions add a modest “View version” link. |
| Release row | Date, format, publisher, relevant identifier, access link. Responsive wrapping instead of a giant tile. |
| Rights summary | Short scoped statement with territory and uncertainty; click/tap/focus opens evidence. Never a green check that implies universal permission. |
| Term label | Usually a quiet text link or low-emphasis tag. Reserve chips for active filters and short groupings. |
| Evidence popover | Claim, source title/link, review context and correction action; dismissible and keyboard-accessible. |
| Empty state | One sentence explaining the gap plus the relevant action, if any. |
| Review comparison | Side-by-side old/new values on wide screens; stacked labeled comparison on mobile. Keep evidence visible beside the decision. |

## 7. Color and icons

There is no assumed universal color for a book versus a film. Choose a local convention and use text/icon labels alongside it. Suggested restrained accents: text/book plum, screen blue, audio amber, interactive teal. Do not encode canonical status, legal permission or trust using medium colors.

Status meaning needs consistent wording: “Index record,” “Planned,” “Disputed,” “Verified representative.” Every badge has a definition accessible by click/focus as well as hover. “Verified representative” must name the represented party/scope; it cannot resemble a universal fact-verification badge.

## 8. Responsive and interaction rules

- Medium widths: header stays side-by-side if readable; body becomes one column when the sidebar would squeeze text.
- Narrow screens: title/actions remain prominent, cover shrinks, long metadata wraps, filters open in an accessible panel. No page-wide horizontal scrolling.
- Do not hide vital facts only to meet an above-the-fold target. Keep good reading order in the DOM even when CSS moves panels beside one another.
- Partial updates preserve useful scroll position, focus and URL state. Loading placeholders match the incoming content's approximate shape.
- Expanded versions and active search filters can be linked/bookmarked. Browser back should restore the prior discovery state.
- Motion is brief and functional; honor reduced-motion settings. No autoplaying poster/video backgrounds.

## 9. Design approval fixtures

Review the same components on:

1. A rich novel with two adaptations and many translations.
2. A sparse short story with no image, unknown year and one anthology link.
3. A film with multiple source works, long credits and disputed authorization.
4. A popular standalone translation page that clearly belongs to a parent work.
5. Search with 20 results, long titles, no-results state, active filters and keyboard navigation.
6. A mobile work page and a 200%-zoom desktop page.

Acceptance checks: readable text/contrast and visible focus; no clipped controls; adjacent blocks where appropriate; no card nesting for ordinary metadata; stable layouts while images load; complete access to popover information without a mouse. Test colors and accessibility rather than declaring the palette compliant by inspection.

## 10. Instruction to the coding agent

Build and review the shared components on the fictional example catalog before applying them to every page. Use one token file and a small component set; do not invent new spacing, radii, type scales or badges on every screen. Present desktop and mobile screenshots of the same fixtures for review. Ask for approval of the visual direction at that concrete stage, not for each CSS choice.

A static mockup will validate composition; a browser prototype must then validate filters, expansion, focus, long text and partial updates. This written specification has not yet performed either validation. Do not treat an attractive empty dashboard as evidence that the real catalog design works.
