# Direct Autonomy Systems GitHub Profile — Implementation Notes

This package is designed to replace the current contents of the public profile repository:

```text
Konfusi0n/Konfusi0n
```

The highest-value change is not simply a prettier banner. The profile is now structured as a compact flagship artifact that answers, in order:

1. Who Cameron Marriott is.
2. What Direct Autonomy Systems builds.
3. What governing thesis makes the work different.
4. How the core systems relate.
5. What the full private portfolio contains.
6. What DAS can build for clients.
7. What is being built toward next.
8. What is and is not publicly proven.

## Package contents

```text
README.md
README_PREVIEW.html
README-preview.png
README-preview-mobile.png
IMPLEMENTATION_NOTES.md
VALIDATION_REPORT.md
assets/
  das-logo.png
  das-logo-transparent.png
  das-profile-banner.png
  das-profile-banner-mobile.png
  das-foundry-map.svg
  das-foundry-map-mobile.svg
  das-foundry-map.png
  das-foundry-map-mobile.png
  social-preview.png
```

Only four assets are required by the README itself:

```text
assets/das-profile-banner.png
assets/das-profile-banner-mobile.png
assets/das-foundry-map.svg
assets/das-foundry-map-mobile.svg
```

`social-preview.png` is intended for the repository’s manual social-preview setting. The logo and rendered map PNGs are included as reusable brand/reference assets.

## Recommended integration

From the root of a local `Konfusi0n/Konfusi0n` checkout, copy in the replacement README and assets:

```powershell
Copy-Item "C:\path\to\das-github-profile\README.md" ".\README.md" -Force
Copy-Item "C:\path\to\das-github-profile\assets\*" ".\assets\" -Force
```

Then inspect the exact change:

```powershell
git diff -- README.md assets/
git diff --check
git status --short
```

After confirming that no other file references the former artwork, remove the superseded profile assets so the repository has one coherent visual system:

```powershell
git rm assets/profile-banner.svg
# Remove only when present:
git rm assets/profile-banner-mobile.svg
git rm assets/system-map.svg
git rm assets/system-map-mobile.svg
git rm assets/systems-ecosystem.png
git rm assets/social-preview.jpg
```

Do not remove an old asset until `git grep` confirms it is no longer referenced:

```powershell
git grep -n "profile-banner\|system-map\|systems-ecosystem\|social-preview.jpg"
```

## GitHub settings to update

### Repository description

Recommended description:

> Founder of Direct Autonomy Systems — bounded AI agents, evidence-aware automation, developer tooling, and deterministic simulations.

### Profile bio

Recommended profile bio:

> Founder, Direct Autonomy Systems. Building bounded AI agents, evidence-aware automation, research systems, developer tooling, and emergent worlds.

### Social preview

In the profile repository, open **Settings → General → Social preview → Edit** and upload:

```text
assets/social-preview.png
```

The supplied image is 1280×640 and optimized below 1 MiB.

### Public contact fields

Use the same identity everywhere:

```text
Company: Direct Autonomy Systems
Website: https://directautonomy.com
Email: founder@directautonomy.com
```

Before merging, verify that the website resolves publicly and that the email address can receive a test message. A dead website link costs more credibility than omitting the link temporarily.

## Why the structure changed

### Company value comes before project inventory

A visitor should understand the business and its differentiator before seeing a long list of internal systems. The first screen now establishes DAS, the bounded-agency thesis, Cameron’s role, and the work categories.

### The four core systems remain memorable

Aureon-Hermes, Mira, Spider Sense, and Automata remain the architectural center because they form a coherent system vocabulary:

```text
Aureon-Hermes  → trust and execution
Mira           → presence and interaction
Spider Sense   → evidence and canon
Automata       → coordination and evolution
```

The complete portfolio is still present, but it is placed in a collapsed section so serious readers can inspect it without forcing every visitor through a wall of project descriptions.

### Private work is described without pretending it is public proof

The README names private systems and explains their role while explicitly separating product direction from deployment, availability, licensing, and independent verification.

### The visuals are responsive and self-contained

The README uses local relative assets, a wide and mobile banner pair, and a wide and mobile foundry-map pair. It does not depend on third-party badge services, animated typing widgets, remote statistics cards, or externally hosted images that can break or undermine the profile’s credibility.

## Recommended commit

```text
feat(profile): establish the Direct Autonomy Systems foundry

Reframe the GitHub profile as the flagship public surface for Cameron Marriott
and Direct Autonomy Systems.

- replace the former pixel-citadel visual system with responsive DAS branding
- lead with the company mission, bounded-agency thesis, and client value
- define Aureon-Hermes, Mira, Spider Sense, and Automata as the core systems
- document the complete private portfolio without overstating public proof
- explain how project laws compound into reusable packs and evaluations
- add client capabilities, engineering doctrine, current direction, and CTA
- add desktop/mobile foundry maps and a repository social preview
- preserve explicit boundaries between local, CI, deployed, serving, and live

The result is a tighter, more credible portfolio artifact that communicates
both the depth of the R&D and the commercial purpose of the company.
```

## Final pre-merge check

```powershell
git diff --check

git grep -n "Directed Autonomy\|Directed Autonomous" -- README.md assets/
# Expected: no matches. The company name is Direct Autonomy Systems.

git grep -n "./assets/" -- README.md
# Confirm every referenced asset exists.
```

Open the profile on both desktop and mobile after pushing. Confirm the banner and foundry map load, the complete-portfolio disclosure expands, the contact links work, and the social preview has been applied in repository settings.
