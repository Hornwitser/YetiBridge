from inspect import getattr_static, signature


class _Literal:
    def __init__(self, characters):
        self.characters = ''
        for char in characters:
            if isinstance(char, _Literal):
                self.characters += char.characters
            else:
                self.characters += char

def split(string):
    """Parse a string into an argument list

    Splits a string of optionally quoted arguments into a list of words
    using a 3 stage process.  Escapes are done with a '\' character and
    it's effect is to turn the next character into a literal with no
    special meaning.  Quotes are then stripped out, and the content
    inside them is preserved, finally whitespace sepparates words.  Note
    that quoted text adjacant non-whitespace or escaped literal is not
    split up into separate words.

    Example: The string 'Augment\ this  "string"_\"battle\" ' is parsed
             into the list ['Augment this', 'string_"battle"'].

    """

    # Turn into a list of characters
    array = list(map(str, string))

    # Turn escaped characters into character literals
    escaped = []
    while array:
        item = array.pop(0)
        if item == '\\' and array:
            escaped.append(_Literal(array.pop(0)))
        else:
            escaped.append(item)

    # Turn quoted string into word literals.
    quoted = []
    while escaped:
        item = escaped.pop(0)
        if item == '"':
            word = []
            while escaped:
                item = escaped.pop(0)
                if item =='"':
                    quoted.append(_Literal(word))
                    break
                else:
                    word.append(item)
            else:
                raise ValueError("unmatched quote")
        else:
            quoted.append(item)

    # Join adjacent sequences of literals and characters not
    # separated by blanks.
    split = []
    word = []
    while quoted:
        item = quoted.pop(0)
        if item != " " and item != "\t":
            word.append(item)
        elif word:
            split.append(_Literal(word))
            word.clear()
    if word:
        split.append(_Literal(word))

    # Turn the sequence of literals into a list of strings
    return list(map(lambda l: l.characters, split))

def command(func):
    """Decorator marking a function as command"""
    func.is_command = True
    return func

def is_command(func):
    """Returns true if the function is a command"""
    return getattr(func, "is_command", False)

def get_commands(obj):
    """Returns the names of all commands in an object"""
    return [name for name in dir(obj) if is_command(getattr_static(obj, name))]

def parameters(func):
    """Generator returing the parameters for a function"""
    for param in signature(func).parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            yield param
        elif param.kind == param.VAR_POSITIONAL:
            while True:
                yield param

    raise TypeError("Extraneous parameters")
