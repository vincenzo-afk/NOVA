# NOVA overview video

This directory contains the editable HyperFrames source and the rendered 36-second, silent NOVA overview used in the repository README.

## Render locally

```bash
npm install
npx hyperframes check
npx hyperframes render --quality high --output renders/nova-overview.mp4
```

The composition is intentionally self-contained: the visuals are inline HTML/CSS and the animation is a single deterministic GSAP timeline. No credentials, external media files, or application runtime dependencies are required to edit the composition.
