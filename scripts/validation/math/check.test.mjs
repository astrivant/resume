import assert from 'node:assert/strict';
import { test } from 'node:test';
import { validate } from './check.mjs';

test('validates inline, display, and GitHub fenced math', () => {
  const source = String.raw`Inline $\mu = 1$.

$$
\sigma^2 = \frac{1}{6}\sum_{i=1}^{6}(L_i-\mu)^2
$$

~~~math
\begin{aligned}e_t &= y_t-p_t \\ p_{t+1} &= p_t + u_t\end{aligned}
~~~
`;
  assert.deepEqual(validate(source, 'valid.md'), { count: 3, errors: [] });
});

test('reports unsupported commands and broken groups at their Markdown location', () => {
  const result = validate('Heading\n\n$\\fraq{1}{2}$\n\n~~~math\n\\frac{1}{\n~~~', 'invalid.md');
  assert.equal(result.errors.length, 2);
  assert.match(result.errors[0], /^invalid.md:3:1:/);
  assert.match(result.errors[1], /^invalid.md:5:1:/);
});

test('ignores math-like examples in ordinary code', () => {
  assert.deepEqual(validate('`$\\unknown$`\n\n```sh\necho "$PATH"\n```\n', 'code.md'), { count: 0, errors: [] });
});

test('rejects unterminated display math and fenced math blocks', () => {
  for (const source of ['$$\nx^2', '```math\nx^2']) {
    assert.match(validate(source, 'unclosed.md').errors[0], /unclosed math block/);
  }
});

test('does not let macros defined in one equation alter later equations', () => {
  const result = validate('$\\gdef\\custom{1}\\custom$ then $\\custom$', 'macros.md');
  assert.equal(result.errors.length, 1);
});
