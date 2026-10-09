// Restore the file control's exact original attributes after the change event has fired.
const input = arguments[0];
const className = arguments[1];
const style = arguments[2];

if (className === null) {
  input.removeAttribute('class');
} else {
  input.setAttribute('class', className);
}

if (style === null) {
  input.removeAttribute('style');
} else {
  input.setAttribute('style', style);
}
