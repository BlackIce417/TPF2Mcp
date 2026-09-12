# Vendored renderer

- `pixi-7.4.3.min.js`: PixiJS 7.4.3 from `https://pixijs.download/v7.4.3/pixi.min.js`
- SHA-256: `712A3E1943B062A907D86C5BB56B67C7B32A3F03B3654768B00B7016D30A24C6`
- License: MIT; see `PIXI-LICENSE.txt`.

The global overview remains SVG for labels and hit testing. Detailed physical
track tiles are rendered by PixiJS/WebGL; the SVG fallback uses the same solid
color rules when WebGL initialization is unavailable.
