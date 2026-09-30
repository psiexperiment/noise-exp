import importlib.resources


def load_app_icon():
    '''
    Load noise_exp/icons/main-icon.png as an Enaml `Icon` for window
    branding.

    Mirrors `cftscal.plugins.branding.load_app_icon`, including the use of
    `importlib.resources` rather than a `__file__`-relative path so this
    keeps working if noise-exp is ever installed as a zipped wheel.

    A plain-Python module rather than something in gui.enaml so that every
    window -- including `CohortDialog`, which has no parent to inherit
    branding from -- can reach it.
    '''
    from enaml.icon import Icon, IconImage
    from enaml.image import Image

    # Chained rather than a multi-argument `joinpath`: noise_exp has no
    # __init__.py, so `files` hands back a MultiplexedPath, which only
    # accepts one component at a time.
    data = (
        importlib.resources.files('noise_exp')
        .joinpath('icons')
        .joinpath('main-icon.png')
        .read_bytes()
    )
    return Icon(images=[IconImage(image=Image(data=data, format='png'))])
