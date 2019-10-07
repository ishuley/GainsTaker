import click
import decimal
import GainsTaker


# add to these as I expand the program {action : description}
supported_choices = {'choices': 'list available choices',
                     'market': 'execute a market order',
                     'pairings': 'show a list of available pairings',
                     'symbols': 'display a list of symbols',
                     'balances': 'display your balances for a given exchange',
                     'exit': 'exit the program'}

@click.command()
@click.option('--action', prompt="What would you like to do? enter 'choices' to see supported choices",
              help='use choices to see available choices')
def choose_an_action(action):  # this will be the first functions the program calls
    action = action.lower()
    if action in supported_choices:
        if action == 'choices':
            choices()
            click.echo()
        if action == 'market':
            click.echo('market executed')
        if action == 'pairings':
            click.echo('pairings executed')
        if action == 'symbols':
            click.echo('symbols executed')
        if action == 'balances':
            click.echo('balances executed')
        if action == 'exit':
            exit()
    else:
        click.echo('unsupported choice, please choose from below:')
        choices()
        click.echo()


def choices():
    click.echo()
    for choice in supported_choices:
        click.echo(choice + ' : ' + supported_choices[choice])
    click.echo()
    choose_an_action()


if __name__ == '__main__':
    choose_an_action()
