# EB Garamond

Vendored from the [CTAN EB Garamond package](https://ctan.org/pkg/ebgaramond),
version 2024-04-23. Font designs are by Georg Duffner and Octavio Pardo; LaTeX
support is maintained by Bob Tennent. See the adjacent upstream README, author
credits, and SIL Open Font License. The upstream README documents the LaTeX
Project Public License for the support files.

Source: `https://mirrors.mit.edu/CTAN/fonts/ebgaramond.zip`

Source SHA-256: `853cbacfe4355e851f520946417c91532d756dcaec756002e75648a13c18f769`

`ebgaramond-texmf.zip` contains the unmodified `latex`, `enc`, and `map` files,
plus `tfm`, `vf`, and `type1` files for Regular, Italic, Bold, and BoldItalic,
arranged into their standard TeX Directory Structure paths. Other font weights
and decorative initials are omitted because the packaged template does not use them.
The compiler extracts this tree into its temporary build directory and supplies
it through `TEXMFHOME`; the template enables `EBGaramond.map`. No global font-map
update or network access is required. `EBGaramond-Regular.otf` is the unmodified
OpenType font used by the skills cloud.

Both files are included in installed wheels and the production container.
