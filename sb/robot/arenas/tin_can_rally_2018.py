# Arena definition for 'Tin Can Rally', the 2017 Smallpeice game.
# (A blatant rip-off of the 2011 game from Student Robotics)
from math import pi

import pygame
import pypybox2d

from sb.robot.arenas import Arena
from sb.robot.arenas.arena import ARENA_MARKINGS_COLOR, ARENA_MARKINGS_WIDTH
from ..game_object import GameObject

WALL_DIAMETER_METRES = 4


class TCRWall(GameObject):
    @property
    def location(self):
        return self._body.position

    @location.setter
    def location(self, new_pos):
        self._body.position = (new_pos[0]-4+self.width/2, new_pos[1]-4+self.height/2)

    @property
    def heading(self):
        return self._body.angle

    @property
    def width(self):
        return self._w

    @property
    def height(self):
        return self._h

    @heading.setter
    def heading(self, new_heading):
        self._body.angle = new_heading

    def __init__(self, arena, w, h):
        self._body = arena._physics_world.create_body(position=(0, 0),
                                                      angle=0,
                                                      type=pypybox2d.body.Body.STATIC)
        hw = w/2
        hh = h/2
        fixture = self._body.create_polygon_fixture([
                                           (-hw, -hh),
                                           (hw, -hh),
                                           (hw, hh),
                                           (-hw, hh)],
                                          restitution=0.2,
                                          friction=0.3)
        self.vertices = fixture.shape.vertices
        self._w = w
        self._h = h
        super().__init__(arena)

    def get_corners(self):
        return [(x+self.location[0], y+self.location[1]) for x, y in self.vertices]


class Token(GameObject):
    grabbable = True

    @property
    def location(self):
        return self._body.position

    @location.setter
    def location(self, new_pos):
        self._body.position = new_pos

    @property
    def heading(self):
        return self._body.angle

    @heading.setter
    def heading(self, new_heading):
        self._body.angle = new_heading

    def __init__(self, arena, number, damping):
        self._body = arena._physics_world.create_body(position=(0, 0),
                                                      angle=0,
                                                      linear_damping=damping,
                                                      angular_damping=damping * 2,
                                                      type=pypybox2d.body.Body.DYNAMIC)
        super(Token, self).__init__(arena)
        self.grabbed = False
        WIDTH = 0.08
        self._body.create_polygon_fixture([(-WIDTH, -WIDTH),
                                           (WIDTH, -WIDTH),
                                           (WIDTH, WIDTH),
                                           (-WIDTH, WIDTH)],
                                          density=1,
                                          restitution=0.2,
                                          friction=0.3)

    def grab(self):
        self.grabbed = True

    def release(self):
        self.grabbed = False

    @property
    def surface_name(self):
        return 'sb/token{0}.png'.format('_grabbed' if self.grabbed else '')


class TCRArena2018(Arena):
    start_locations = [(-3.6, -3.6),
                       (3.6, 3.6)]

    start_headings = [pi / 2,
                      -pi / 2]

    def __init__(self, objects=None):
        super().__init__(objects)
        self._init_walls()
        self._init_tokens()

    def _init_tokens(self):
        # Clockwise from top left
        token_locations = [
            (-0.5, -3),
            (3, -3),
            (3, -0.5),
            (0.5, 3),
            (-3, 3),
            (-3, 0.5),
        ]

        for i, location in enumerate(token_locations):
            token = Token(self, i, damping=5)
            token.location = location
            token.heading = 0
            self.objects.append(token)

    def _init_walls(self):
        self.walls = set()
        wall = TCRWall(self, 1.22, 2.44)
        wall.location = (1.5, 1.55)
        self.objects.append(wall)
        self.walls.add(wall)

    def draw_background(self, surface, display):
        super().draw_background(surface, display)

        def line(start, end, colour=ARENA_MARKINGS_COLOR, width=ARENA_MARKINGS_WIDTH):
            pygame.draw.line(surface, colour,
                             display.to_pixel_coord(
                                 start), display.to_pixel_coord(end),
                             width)

        def line_opposite(start, end, **kwargs):
            start_x, start_y = start
            end_x, end_y = end
            line((start_x, start_y), (end_x, end_y), **kwargs)
            line((-start_x, -start_y), (-end_x, -end_y), **kwargs)

        def line_symmetric(start, end, **kwargs):
            start_x, start_y = start
            end_x, end_y = end
            line_opposite(start, end, **kwargs)
            line_opposite((start_y, start_x), (end_y, end_x), **kwargs)

        # Section lines
        line_symmetric((0, WALL_DIAMETER_METRES / 2), (0, 4))

        # Starting zones
        line_opposite((3, 3), (3, 4))
        line_opposite((3, 3), (4, 3))

        # Centre Wall
        for wall in self.walls:
            vectors = wall.get_corners()
            colour = (0x00, 0x80, 0xd6)
            width = 7
            line(
                (vectors[0]), (vectors[1]),
                colour=colour,
                width=width
            )
            line(
                (vectors[1]), (vectors[2]),
                colour=colour,
                width=width
            )
            line(
                (vectors[2]), (vectors[3]),
                colour=colour,
                width=width
            )
            line(
                (vectors[3]), (vectors[0]),
                colour=colour,
                width=width
            )
