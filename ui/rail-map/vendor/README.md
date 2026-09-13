# Vendored renderer

- `pixi-7.4.3.min.js`: PixiJS 7.4.3 from `https://pixijs.download/v7.4.3/pixi.min.js`
- SHA-256: `712A3E1943B062A907D86C5BB56B67C7B32A3F03B3654768B00B7016D30A24C6`
- License: MIT; see `PIXI-LICENSE.txt`.
- `jquery-4.0.0.min.js`: jQuery 4.0.0 full minified build from `https://code.jquery.com/jquery-4.0.0.min.js`
- SHA-256: `39A546EA9AD97F8BFAF5D3E0E8F8556ADB415E470E59007ADA9759DCE472ADAA`
- License: MIT; the upstream copyright and license notice is retained in the file header.

The global overview remains SVG for labels and hit testing. Detailed physical
track tiles are rendered by PixiJS/WebGL; the SVG fallback uses the same solid
color rules when WebGL initialization is unavailable.
