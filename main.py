import pygame
pygame.init()
screen=pygame.display.set_mode((800,600))
pygame.display.set_caption("Resident Evil")
while True:
    for event in pygame.event.get():
        if event.type==pygame.QUIT:
            pygame.quit()
            exit()
    screen.fill((255,255,255))
    pygame.display.update()