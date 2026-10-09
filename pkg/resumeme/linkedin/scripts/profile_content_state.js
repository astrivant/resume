// A heading can render before its neighboring cards. Do not scroll past their loading placeholders.
const main = document.querySelector('main');
const primary = main?.querySelector('section[aria-label="Primary content"]') || main;

if (!primary) {
  return null;
}

const viewportHeight = document.documentElement.clientHeight;
const visible = (node) => {
  const rect = node.getBoundingClientRect();
  const style = getComputedStyle(node);
  return rect.height > 0 && rect.width > 0 && rect.bottom > 0 && rect.top < viewportHeight
    && style.display !== 'none' && style.visibility !== 'hidden';
};

// Current skeleton cards have section containers but no heading or readable content yet.
// Ignore empty optional containers and carousels; neither proves that a real profile section exists.
const pending = [...primary.querySelectorAll('section, [aria-busy="true"], [role="progressbar"]')].some((node) => {
  if (!visible(node)) {
    return false;
  }

  if (node.getAttribute('aria-busy') === 'true' || node.getAttribute('role') === 'progressbar') {
    return true;
  }

  return node.childElementCount > 0 && !node.innerText.trim()
    && !node.matches('[data-testid="carousel"], [aria-roledescription="carousel"]')
    && !node.querySelector('h1, h2, h3, img, video, iframe, svg, [role="img"]');
});

// Include geometry so a lazy layout shift restarts the quiet interval even if its text is unchanged.
return pending ? null : JSON.stringify([primary.innerText, primary.scrollHeight, primary.scrollWidth]);
