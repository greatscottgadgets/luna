
# -- Project information -----------------------------------------------------

project = 'LUNA'
copyright = '2020 Great Scott Gadgets'
author = 'Katherine J. Temkin'

# -- General configuration ---------------------------------------------------

master_doc = 'index'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon'
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']


# -- Options for HTML output -------------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['status.css']


# -- Options for automatic documentation -------------------------------------

# Skip documenting Tests.
def autodoc_skip_member_handler(app, what, name, obj, skip, options):
    return \
        name.endswith("Test") or \
        name.startswith('_')  or \
        (name == "elaborate")

def setup(app):
    app.connect('autodoc-skip-member', autodoc_skip_member_handler)
