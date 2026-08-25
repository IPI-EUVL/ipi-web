# Frontend Assets

Place imported UI artwork here, for example `src/assets/ipi-logo.png` or `src/assets/ipi-logo.svg`.

Import files from components so Vite fingerprints and bundles them:

```ts
import ipiLogo from '../assets/ipi-logo.svg'
```

Use `frontend/public/` only for resources that need a stable root-relative URL rather than an imported bundle asset.