// poster.html を 3240x1080 で書き出し、1080x1080 ×3 に分割する
// 使い方: node tools/render.js
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const root = path.resolve(__dirname, '..');
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 3240, height: 1080 } });
  await page.goto('file://' + path.join(root, 'poster.html'));
  await page.waitForTimeout(300);
  const el = await page.$('#poster');
  await el.screenshot({ path: path.join(root, 'output/panorama_3240x1080.png') });
  for (let i = 0; i < 3; i++) {
    await page.screenshot({
      path: path.join(root, `output/feed_${i + 1}.png`),
      clip: { x: i * 1080, y: 0, width: 1080, height: 1080 },
    });
  }
  await browser.close();
})();
