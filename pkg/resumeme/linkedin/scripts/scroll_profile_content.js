// Find LinkedIn's scrollable profile pane, falling back to the document scroller.
const main = document.querySelector('main');
let node = main?.querySelector('section[aria-label="Primary content"]') || main;
let target = document.scrollingElement;

while (node && node !== document.body) {
  if (['auto', 'scroll'].includes(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) {
    target = node;
    break;
  }

  node = node.parentElement;
}

// Advance by most of the viewport so lazy content loads with overlapping snapshots.
if (arguments[0] === 'top') {
  target.scrollTop = 0;
} else {
  target.scrollTop += Math.max(target.clientHeight * 0.8, 600);
}

return target.scrollTop + target.clientHeight >= target.scrollHeight - 5;
