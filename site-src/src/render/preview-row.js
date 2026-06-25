import { escapeHtml } from '../util/escape.js';
import { fmtPair, fmtVid } from './fmt.js';
import { highlightText, reasonBadge } from './match.js';

function boardSampleText(preview) {
  const sample = preview.knownBoards?.sample || [];
  if (!sample.length) return '';
  return sample
    .map((board) => board.name || board.board_id)
    .filter(Boolean)
    .slice(0, 3)
    .map(escapeHtml)
    .join(', ');
}

function productSampleHtml(preview, query = '') {
  const sample = preview.knownProducts?.sample || [];
  if (!sample.length) return '';
  return sample
    .slice(0, 5)
    .map((product) => {
      const pair = fmtPair(product.vid, product.pid, 'field-hit');
      const name = highlightText(product.product || '', query, [
        product.vid,
        product.pid,
        `${product.vid}:${product.pid}`,
      ]);
      return `${pair} ${name}`;
    })
    .join(', ');
}

function renderVidPreview(preview, query = '') {
  const boardTotal = preview.knownBoards?.total || 0;
  const productTotal = preview.knownProducts?.total || 0;
  const boardSample = boardSampleText(preview);
  const productSample = productSampleHtml(preview, query);
  const productSampleMarkup = productSample
    ? `<div class="preview-sample">Product samples: ${productSample}</div>`
    : '';
  const boardSampleMarkup = boardSample
    ? `<div class="preview-sample">Board samples: ${boardSample}</div>`
    : '<div class="preview-sample empty">No linked board definitions found yet.</div>';
  const vendor = preview.vendor || 'Unknown vendor';

  return (
    '<div class="preview-row vid-preview search-hit exact-hit">' +
      '<div class="preview-main">' +
        '<div class="preview-title-row">' +
          '<span class="tag vendor">USB VID</span>' +
          `${fmtVid(preview.vid, 'field-hit')}` +
          `<span class="preview-title">${highlightText(vendor, query, [preview.vid])}</span>` +
          `${reasonBadge(preview)}` +
        '</div>' +
        '<div class="preview-stats" aria-label="VID summary">' +
          `<span><strong>${Number(boardTotal).toLocaleString()}</strong> known boards</span>` +
          `<span><strong>${Number(productTotal).toLocaleString()}</strong> USB products</span>` +
        '</div>' +
        `${productSampleMarkup}` +
        `${boardSampleMarkup}` +
      '</div>' +
    '</div>'
  );
}

export function renderPreviewRow(preview, query = '') {
  if (preview.kind === 'vid') return renderVidPreview(preview, query);
  return (
    '<div class="preview-row search-hit">' +
      `<span class="preview-title">${escapeHtml(preview.kind || 'preview')}</span>` +
    '</div>'
  );
}
