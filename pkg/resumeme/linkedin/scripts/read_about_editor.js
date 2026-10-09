// Read authored text nodes and structural breaks without capturing layout-dependent visual wrapping.
const root = arguments[0];

const read = (node) => {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.nodeValue || '';
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return '';
  }

  if (node.tagName === 'BR') {
    return '\n';
  }

  const text = Array.from(node.childNodes, read).join('');
  return node !== root && ['P', 'DIV', 'LI'].includes(node.tagName) ? `${text}\n` : text;
};

return read(root).replace(/\n+$/, '');
