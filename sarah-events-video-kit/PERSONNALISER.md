# Personnaliser le kit

Ce kit arrive générique. Tel quel, il monte comme moi : mes couleurs, mon rythme, mon type de
contenu. Ce n'est pas ce que tu veux.

Avant de monter quoi que ce soit, tu vas le rendre tien. Une seule fois, une quinzaine de minutes.

## Comment faire

Ouvre **Claude Code dans ce dossier** et dis-lui simplement :

> Personnalise le kit.

Il chargera tout seul la marche à suivre.

Si tu préfères passer par Claude dans ton navigateur, ouvre une conversation, **joins ce dossier**
et colle tout ce qui suit la ligne. Attention, Claude dans le navigateur ne peut pas modifier tes
fichiers directement : il te rendra les fichiers réécrits, que tu remplaceras à la main. Claude
Code fait le travail en entier, c'est le chemin recommandé.

---

Tu configures un kit de montage vidéo automatique pour son nouveau propriétaire. Le kit est
générique : il porte les réglages de son auteur. Ton travail est de l'interroger, puis de réécrire
le kit pour qu'il soit le sien avant qu'il monte sa première vidéo.

## Comment tu mènes l'entretien

Pose les blocs de questions **un par un**. Attends sa réponse avant de passer au suivant. Ne pose
jamais les huit blocs d'un coup, il abandonnera.

Il a le droit de répondre « je ne sais pas » ou « choisis pour moi ». Dans ce cas, propose une
valeur, explique en une phrase pourquoi, et continue. Ne le bloque jamais sur une question.

Ne devine rien qu'il ne t'a pas dit. Tout ce que tu écris dans ses fichiers doit venir d'une de ses
réponses ou d'un défaut que tu lui as annoncé à voix haute.

## Avant d'écrire quoi que ce soit

Copie dans `.original/` chaque fichier que tu t'apprêtes à modifier, en gardant l'arborescence.
C'est son filet : il doit pouvoir revenir en arrière sur n'importe quel fichier, tout seul, sans
toi. Si `.original/` existe déjà, ne l'écrase pas, la personnalisation a déjà eu lieu une fois.

## Les huit blocs

**1. Son contenu.** Ce qu'il filme, sur quel sujet, pour qui. Ce qu'on voit à l'écran dans ses
vidéos quand ce n'est pas son visage : des captures de logiciel, des lieux, des objets, des
documents, des gens, rien du tout.

**2. Où il publie.** Instagram, TikTok, YouTube, LinkedIn, plusieurs. Et lesquelles comptent le
plus. C'est ce qui décide le format vertical ou horizontal et la cible de normalisation sonore.

**3. La forme de ses vidéos.** Sa tête en plein cadre, ou un split-screen avec quelque chose
d'animé au-dessus et sa face cam en dessous. S'il ne sait pas, demande-lui une de ses vidéos
récentes et regarde.

**4. Sa marque.** Sa couleur de fond, sa couleur d'accent, sa couleur de texte. Ses polices.
Rappelle-lui de déposer ses fichiers de police dans `fonts/`, en `.ttf` ou `.otf`, jamais en
`.woff2`. Une fois déposées, lance `node engine/lib/font-name.mjs fonts/<son-fichier>` et écris le
nom que la commande affiche, jamais le nom du fichier : c'est le seul que le moteur de sous-titres
sait chercher. S'il n'a pas de polices, dis-le clairement, il pourra dérusher sans, mais pas
sous-titrer.

**5. Ses sous-titres.** Gros ou discrets. Majuscules ou casse naturelle. Avec ou sans boîte
derrière. Un mot à la fois ou trois. Haut ou bas de l'image. Si ça l'aide, décris-lui deux styles
opposés et demande lequel ressemble le plus à ce qu'il veut.

**6. Son rythme.** Montage incisif, qui colle les phrases presque bord à bord, ou plus respirant,
qui laisse un souffle entre elles. C'est le réglage qui change le plus la sensation du résultat, et
c'est le plus difficile à décrire : donne-lui un repère concret tiré de comptes qu'il connaît.

**7. Son vocabulaire.** Les mots que la transcription va systématiquement écorcher : noms de
marques, prénoms, jargon de son métier, anglicismes. Demande-lui-en cinq à dix. Ils seront corrigés
d'office dans ses sous-titres, il n'aura plus jamais à les reprendre à la main.

**8. Sa langue et sa transcription.** La langue qu'il parle dans ses vidéos. Puis s'il a une clé
ElevenLabs, une clé OpenAI, ou aucune des deux. Si aucune, dis-lui laquelle prendre et pourquoi
avant de continuer.

## Ce que tu réécris ensuite

Lis chaque fichier avant de le modifier. Ne modifie que ce que ses réponses justifient.

**`brand.json`** en entier. C'est la surface principale. Format, couleurs, polices, style complet
des sous-titres, cadrage et jonction du split-screen, cible sonore, langue et fournisseur de
transcription, agressivité de la coupe, et ses mots à corriger d'office. Les champs à `null` se
déduisent tout seuls : laisse-les à `null` sauf s'il a demandé autre chose explicitement.

**`.claude/skills/video-montage/SKILL.md`**, la section sur la hiérarchie visuelle. Elle est écrite
pour du contenu technique, avec des captures de logiciel en haut de la hiérarchie. Réécris-la pour
**son** contenu à lui, d'après le bloc 1. Quelqu'un qui filme des chantiers, des plats ou des
salles de sport n'a rien à faire d'une capture d'écran. C'est cette section qui décide de ce que
son montage affiche, donc c'est elle qui doit cesser d'être la mienne.

**Les déclencheurs des deux compétences**, dans leur en-tête `description`. Mets-y les mots qu'il
emploie lui, dans sa langue, pour parler de ses vidéos.

**`engine/montage/template.html`** via `node engine/montage/apply-brand.mjs`, pour que la
composition animée parte à sa charte.

**Le reste du moteur** si, et seulement si, une de ses réponses l'exige et qu'aucun réglage ne
permet d'y arriver. Dans ce cas, dis-lui explicitement ce que tu touches et pourquoi, avant de le
faire.

Quatre mécanismes portent le résultat. Tu peux régler leurs valeurs, ne remplace pas leur principe
sans le lui dire en face : la transcription garde les hésitations au lieu de les nettoyer, les
reprises sont trouvées en alignant ce qu'il a dit sur ce qu'il comptait dire, la coupe tombe
toujours dans un silence calibré sur son propre fichier, et la vérification finale mesure le son
aux raccords au lieu de relire le texte. Casser l'un des quatre casse le kit en silence : il
continuera de produire un fichier, simplement mauvais.

## Avant de lui rendre la main

Lance `node doctor.mjs` et montre-lui le résultat. Puis relis `brand.json` et vérifie qu'aucun
champ ne contredit ce qu'il t'a répondu.

Écris enfin `PERSONNALISATION.md` à la racine : ce qu'il t'a répondu, ce que tu as changé fichier
par fichier, ce que tu as laissé par défaut, et ce qui lui reste à faire lui-même, ses polices en
premier si elles manquent encore. C'est ce fichier qu'il relira dans six mois quand il voudra
changer d'avis, et c'est celui qu'il te redonnera pour reprendre l'entretien là où vous l'avez
laissé.

Termine en lui disant, en trois lignes, la commande exacte qui monte sa première vidéo.
