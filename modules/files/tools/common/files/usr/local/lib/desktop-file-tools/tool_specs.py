"""Small declarative descriptions for the common native interface."""


def option(name, title, kind='text', default='', choices=()):
    return dict(name=name, title=title, kind=kind, default=default, choices=choices)


def action(
    name, title, group, fields=(), output=True, minimum=1, preview=False, description=''
):
    return dict(
        id=name,
        title=title,
        group=group,
        fields=fields,
        output=output,
        minimum=minimum,
        preview=preview,
        description=description,
    )
