# Plan : un successeur léger à dev-pipeline

Rédigé le 2026-09-17. Statut : **validé le 2026-09-17 ; étapes 1 et 2 construites**
(dépôt `dev-ai`, commande `dev-ai` ; l'état courant est dans
`docs/roadmap.md`). Utilisateur : une seule personne, sur plusieurs dépôts, avec des modèles
frontière (Fable 5.1, Opus 5, gpt-6-astra). Ce plan prend la suite de
`model-era-adaptation.md` (2026-09-11) : il en garde les principes et la phase 4,
et remplace ses phases 1 à 3 — la chirurgie sur place — par un outil neuf et
petit.

## Pourquoi la chirurgie sur place ne suffit pas

| Mesure | 11 sept. | 17 sept. |
|---|---|---|
| Correctifs du pipeline sur 30 jours | 158 / 234 commits | 169 / 251 (67 %, inchangé) |
| Suite de tests | — | 3 305 tests, non terminée en 90 min |
| Variables `DP_*` distinctes | — | 466 |
| `run-task.md`, contrat interprété par un LLM | — | 1 042 lignes |
| Modules du « noyau » | — | `dp-worktree.sh` 5 014 l., `dp-go-driver.py` 4 693, `_lib.sh` 3 626, `human-gate.py` 2 035 |

Six jours de correctifs (lots H à O) n'ont pas bougé le taux. Le défaut est
structurel : un orchestrateur LLM qui lit un contrat de mille lignes, cinq
runners, et un appareil de preuve signée bâti pour un modèle qui ment. Le noyau
lui-même est trop gros pour être « repris » : il faut le réécrire petit.

## Ce que les mesures disent de garder et de retirer

le banc (un dépôt de modules Odoo), 53 tâches (32 haut, 20 moyen, 1 faible), lecture du 2026-09-17 :

| Étape | Verdicts non-pass | Décision |
|---|---|---|
| Relecteur | 15 / ~68 ; **9 des 12 reprises** | garder, en une seule passe |
| Codex review / adversarial | 6 / 10 et 5 / 7 exécutions réelles | garder : c'est *le modèle différent* qui attrape (TASK-045, 046 : FAIL après un pass sécurité du même fournisseur) |
| Porte de tests hôte | 3 / 71 | garder : bon marché, déterministe |
| Conseil | **0 / 22** | retirer |
| Porte de conception | 2 / 77 | retirer comme étape |
| Validation finale | 3 blocages **après** approbation humaine, sur dette d'instrumentation (TASK-046, 048, 056) | retirer |
| Arrêts humains | 31 `before_coding` + 42 `before_merge` | garder `before_merge` sur impact, retirer `before_coding` |

Défauts réels attrapés par relecture et pas par les tests : TASK-023 (CRITICAL,
collision d'identité), 024 (TLS/SNI), 036 (1 CRITICAL, 3 HIGH), 038 (invariant
contournable), 045 (AccessError), 047 (HIGH). Cérémonie pure : TASK-039 (« c'est
la preuve qui échoue, pas le comportement »), TASK-051 (front-matter).
Nuance : sur un autre dépôt, 5 reprises pour 515 tâches. Le rendement de la relecture
dépend du dépôt ; elle se route donc sur l'impact, pas partout.

## Le changement de fond : le modèle de menace

| | dev-pipeline | successeur |
|---|---|---|
| Le modèle | ment, invente des succès, sort du périmètre | compétent ; vise la mauvaise cible, en fait trop, réussit ses propres tests, laisse des défauts subtils en code sensible |
| L'orchestrateur | un LLM qui interprète un contrat | du code déterministe, aucun LLM |
| Conséquence | reçus signés, entrées scellées, attestation d'autorat, registre immuable, budgets de reprise | rien de tout cela |

## Le successeur en une page

Nom de travail : `dp-lite`. Une CLI Python, stdlib seule. Le développement se
fait dans le harnais natif (Claude Code, Codex) ; `dp-lite` ne planifie pas,
n'exécute pas, ne route aucun modèle. Il **contient et prouve** : `start`,
`check`, `review`, `land` (le flux courant est dans `design.md`).

- **Relecture par un autre modèle**, d'abord routée sur l'impact du diff
  (ACL, migrations, API publique, secrets) ; depuis le 2026-09-20, sur tout
  changement hors documentation descriptive, les motifs ayant manqué un garde retiré.
- **Brief du relecteur** : périmètre et décisions prises sans instruction
  d'abord, puis le diff (acquis de la phase 0 du plan précédent).
- **Un échec ne consomme rien** : on corrige, on relance `dpl check`. Pas de
  budget de reprise, pas de rescue, pas de registre à réparer.
- **Configuration** : un `dev-ai.json` par dépôt. Le `dp-project.json` n'est plus
  lu depuis le 2026-09-18 : sa suite e2e s'y perdait en silence (5 dépôts sur 5).
- **Télémétrie** : une ligne JSONL par commande, horodatée. Préparation, run et
  attente humaine s'en déduisent sans instrumentation.

## Ce qui est repris, ce qui ne l'est pas

Repris : les motifs d'impact de `dp_validators/security_impact.py`, et comme
**tests** les leçons payées cher (les tests tournent dans le worktree et y
importent le code, TASK-068 ; une base par run ; le relecteur voit le patch
exact). Non repris : les 25 validateurs, les 16 contrats, les 31 skills, les
cinq adaptateurs de runner, le routage par tiers, `dp-go-driver.py`,
`human-gate.py`, `dp-run-telemetry.py`. L'installeur, lui, est revenu : voir
`scripts/install.sh`, 62 lignes de compétence hors dépôt étaient une dérive.

## Étapes

Étapes 0 à 2 faites : gel de dev-pipeline, puis `start`, `check`, `land` et la
télémétrie, puis `review`. Étape 3 en cours, quatre tâches livrées sur le banc,
médiane 3 h 52. Critères inchangés, repris dans `roadmap.md` et `AGENTS.md` :
succès si la médiane ouverture → merge est au moins divisée par deux (référence
4,3 à 23,3 h) sans défaut d'après-merge ; arrêt si un budget est dépassé deux
fois, ou s'il faut plus d'un commit de correction par tâche livrée.

## Sort de dev-pipeline

Gelé, pas supprimé. Il reste la voie pour ce que `dp-lite` ne sait pas encore
porter. La phase 4 de `model-era-adaptation.md` continue (retraits derrière
drapeau, preuves ci-dessus). Après vingt tâches livrées par `dp-lite` sans
défaut rattrapable : archivage.

## Risques et inconnues

| Risque | Parade |
|---|---|
| Le successeur devient à son tour « un projet entier » | budget vérifié par test, critère d'arrêt chiffré, gel des gardes sans cas réel |
| L'appareil de preuve signée attrapait des choses que je n'ai pas mesurées | **mesuré sur le banc le 2026-09-17** : sur 53 tâches, aucune violation de périmètre ni preuve falsifiée attrapée par cet appareil dans les notes du registre ; les douze blocages persistés sont des tests, des relectures, des décisions humaines ou de la validation finale. Reste à faire sur un autre dépôt. Le contrôle de périmètre, lui, est gardé : il coûte dix lignes |
| La classification « vrai défaut / cérémonie » vient des notes du registre, pas d'une relecture des diffs | relire les six cas avant de figer le routage de la relecture |
| Un défaut passe sans relecture sur un diff jugé neutre | depuis le 2026-09-20, seule la documentation descriptive échappe à la relecture ; mesurer les constats confirmés, réfutés et manqués sur les vingt premières tâches |
| Hypothèse « utilisateur unique » | si une équipe l'utilise un jour, rouvrir la question de la provenance |

## Décisions

Dépôt `dev-ai`, commande `dev-ai`, banc d'essai sur un dépôt de modules Odoo.
Les écarts assumés depuis cette page sont dans `design.md` : configuration lue
dans le checkout principal ; depuis le 2026-09-20, plus de terminal ni de motifs
d'impact — l'invite du harnais et le mandat enregistré au `start` approuvent, tout
changement hors documentation descriptive est relu, les constats bloquants se
résolvent avec preuve.
