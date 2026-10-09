// Temporarily expose LinkedIn's hidden file input so Selenium can select the staged PDF.
const input = arguments[0];
input.classList.remove('hidden');

for (const [name, value] of Object.entries({
  display: 'block',
  visibility: 'visible',
  position: 'fixed',
  left: '0',
  top: '0',
  width: '1px',
  height: '1px',
  opacity: '0.01',
})) {
  input.style.setProperty(name, value, 'important');
}
