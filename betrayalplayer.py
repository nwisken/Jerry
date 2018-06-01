class BetrayalPlayer:
    """
    Class used to hold all the values a a character
    can have in Betrayal at House on Hill
    """

    def __init__(self, name, might, speed, sanity, knowledge):
        self.name = name
        self.might = might
        self.speed = speed
        self.sanity = sanity
        self.knowledge = knowledge

    def __str__(self):
        return ("{}\nMight: {}\nSpeed: {}\nSanity: {}\nKnowledge: {}"
                .format(self.name, self.might, self.speed, self.sanity, self.knowledge))