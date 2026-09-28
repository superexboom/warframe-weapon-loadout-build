/* Native enemy icon identities come from the offline asset manifest. */
function createEnemyThumbnail(enemy, faction) {
  const thumb = document.createElement('div');
  thumb.className = 'enemy-thumb';
  thumb.dataset.imageStatus = enemy.imageStatus || 'missing';
  const fallback = document.createElement('span');
  fallback.className = 'enemy-thumb-placeholder';
  const labels = { Grineer: 'G', Corpus: 'C', '感染体': 'I', Orokin: 'O', '合一众': '合', Sentient: 'S', Tenno: 'T', '双衍王境': '双' };
  fallback.textContent = labels[faction] || '?';
  fallback.title = '暂无该敌人的专属图片 · ' + (faction || '未知派系');
  fallback.setAttribute('aria-label', fallback.title);
  thumb.append(fallback);
  if (typeof enemy.imageAsset !== 'string' || !enemy.imageAsset.startsWith('/assets/enemies/art/')) return thumb;
  const image = document.createElement('img');
  image.alt = enemy.nameZh || enemy.nameEn || enemy.displayName || '敌人';
  image.loading = 'lazy';
  image.decoding = 'async';
  image.style.opacity = "0";
  image.addEventListener('load', () => { image.style.opacity = "1"; fallback.hidden = true; });
  image.addEventListener('error', () => { image.remove(); fallback.hidden = false; thumb.dataset.imageStatus = 'load-error'; });
  if (enemy.imageInherited) thumb.title = '使用游戏原始配置继承的图标';
  image.src = enemy.imageAsset;
  thumb.append(image);
  return thumb;
}