---
name: frame-task
description: "Cadre une tâche dev-ai avant `dev-ai start` et rend une fiche prête pour `/dev-ai` — critères de « fini » vérifiables, périmètre, découpage, spec d'invariants là où elle paie, mandat, et ce qui restera à la charge de l'opérateur. Utilise ce skill quand l'utilisateur demande de cadrer, définir, préparer ou découper une tâche dans un dépôt migré vers dev-ai (un `dev-ai.json` à la racine), quand il hésite sur la tâche à lancer, quand un finding de revue sort du but de la tâche en cours, et pour tout défaut trouvé après un merge : son but doit alors commencer par `Fixes-task: <slug>`, et c'est ce skill qui le pose. Une demande de travail dont le but est déjà clair va directement à `/dev-ai`, sans cadrage. Il ne lance rien."
---

# Cadrer une tâche dev-ai

dev-ai prouve que le patch reste sur sa cible, qu'il est testé et qu'un autre modèle l'a relu. Il ne prouve pas que la cible est la bonne : c'est le cadrage qui la fixe, et c'est là que l'opérateur pèse le plus. Rends-lui une fiche nette en lui prenant le moins de temps possible ; `/dev-ai` exécute ensuite.

Trois règles tiennent le reste :

- **Tu ne lances rien.** Pas de `dev-ai start`, pas de commit, pas d'écriture dans le dépôt hors de `.dev-ai/`, que git ignore ; la lecture et `dev-ai status`, qui n'écrit qu'une ligne de journal, sont permis. Le seul fichier que tu écris est le brouillon de spec, sous `.dev-ai/frames/`.
- **Une seule série de questions.** L'outil qui a précédé dev-ai arrêtait l'opérateur des dizaines de fois par tâche. Ici, tu décides tout ce qui n'est pas à lui et tu l'écris dans la fiche ; tu ne lui demandes que ce qui est à lui (étape 6), en un seul message.
- **Tu ne classes aucun risque et tu ne bloques rien.** dev-ai fait relire tout patch hors documentation, quoi qu'il arrive. Le cadrage sert seulement à ce que les tests et la relecture visent juste.

## 1. Situer la demande

| Source | Ce que ça change |
|---|---|
| Une demande claire et bornée | Pas de cadrage : dis-le et renvoie à `/dev-ai`. Un arrêt avant chaque tâche est ce que dev-ai a écarté. |
| Un besoin | Le but dit ce que « fini » veut dire. |
| Un défaut trouvé après le merge d'une tâche dev-ai | Le but commence par `Fixes-task: <slug d'origine>`, suivi de ce que « fini » veut dire : c'est ainsi que la routine des vingt tâches compte les défauts après merge. Retrouve le slug ci-dessous. |
| Un finding de revue dans le but de la tâche en cours | Pas de nouvelle tâche : il se confirme ou se réfute dans `/dev-ai`. Dis-le et arrête-toi. |
| Un finding de revue hors de ce but (code existant, autre module) | Une nouvelle tâche, jamais un `scope-add` qui l'absorberait. Si le code visé vient d'une tâche mergée, c'est un défaut : `Fixes-task`. |

**Retrouver la tâche d'origine d'un défaut**, depuis la ligne fautive ; sans ligne précise, trouve-la d'abord, du symptôme au code qui le produit. Le merge qui a apporté un commit est le plus ancien merge d'une branche `dev-ai/…` descendant de ce commit dont le premier parent ne le contenait pas encore. Sans ce dernier test, un commit fait directement sur la branche de base serait attribué à la première tâche mergée après lui.

```bash
c=$(git log -1 -s --format=%H -L <ligne>,<ligne>:<fichier>)
test -n "$c" || echo "ligne introuvable"
o=""
# git log va du plus récent au plus ancien : la dernière affectation garde le plus ancien.
for m in $(git log --merges --ancestry-path --format=%H "$c"..HEAD); do
  s=$(git log -1 --format=%s "$m")
  [[ $s == "merge dev-ai/"* || $s == "Merge branch 'dev-ai/"* ]] && ! git merge-base --is-ancestor "$c" "$m^1" && o="$s"
done
echo "$o"
```

La sortie est `merge dev-ai/<slug>: <but>`, le message que pose `land --merge`, ou `Merge branch 'dev-ai/<slug>'`, celui que git pose quand une tâche livrée en `commit` est mergée à la main sans `-m`. Vide : aucun merge de tâche n'a apporté le commit. Une tâche livrée en `commit` puis mergée en avance rapide n'en laisse pas : cherche-la parmi les tâches `committed` de `dev-ai status`. C'est celle dont le `head_sha` de `.dev-ai/tasks/<slug>/landing.json` contient le commit, et dont le `base_sha` de `check.json`, dans le même dossier, ne le contient pas ; `git merge-base --is-ancestor <commit> <sha>` le dit. Aucune : pas de `Fixes-task`, et la fiche dit que l'origine n'a pas été trouvée. « ligne introuvable » : le fichier a été renommé ou la ligne a bougé ; demande-la dans la version actuelle plutôt que de conclure. Si le hook de l'opérateur bloque une commande, ne la contourne pas : reformule-la avec les formats de git (`--format`), sans extraction de colonne ni expansion `${…}`. Ce bloc-ci passe.

## 2. Lire le terrain

- Le dépôt est migré : `dev-ai.json` à la racine et la note « Working with dev-ai » dans `AGENTS.md`. Sinon, dis-le et arrête-toi : il n'y a pas de tâche dev-ai à cadrer.
- Lis `test_command` dans `dev-ai.json` : c'est la seule chose que dev-ai garantit. Note ce qu'il exécute et ce qu'il n'exécute pas (e2e, tests d'ACL, scanners, mise à jour de module) ; l'étape 3 en dépend.
- Lis `AGENTS.md` et les documents de décision qu'il désigne (roadmap, design, ce qui n'est « pas prévu ») : leurs conventions priment sur les seuils de ce skill. Une demande qui contredit une décision déjà prise se signale en tête de ton message, avant la fiche.
- Si `AGENTS.md` fixe un budget chiffré (lignes de code, durée de la suite), mesure où il en est : c'est souvent lui, plus que les 600 lignes de l'étape 4, qui borne la tâche.
- `dev-ai status` : une tâche ouverte qui couvre déjà la demande se reprend, elle ne se double pas.
- Explore juste assez pour nommer les fichiers touchés, leurs appelants et les tests existants. Le plan d'implémentation est le travail de `/dev-ai`, pas le tien.

## 3. Écrire « fini » en critères vérifiables

Un critère est un comportement observable, telle entrée donnant tel résultat, pas une activité : « refactorer X » n'en est pas un. Pour chacun, dis ce qui le prouvera :

- **un test**, écrit d'abord, que `test_command` exécutera : c'est garanti ;
- **la recette de l'opérateur**, quand `test_command` ne peut pas le prouver (parcours dans l'interface, rendu d'un rapport, performance sur volumes réels, migration sur une copie de production) : c'est à sa charge, et la fiche le dit.

Un test qui ne ferait qu'épingler un texte ou une valeur, sans comportement derrière, ne prouve rien : c'est de la recette. Un critère qu'aucun test ni aucune recette ne peut prouver est flou : reformule-le avant d'aller plus loin. C'est le signe le plus sûr qu'une demande n'est pas mûre.

## 4. Périmètre et découpage

- `--paths` : le plus étroit qui contienne le changement, les tests qui le prouvent, et les tests, commentaires et docs existants qui affirment ou décrivent le comportement changé : cherche-les avant de rendre la fiche (`rg` sur le nom de la méthode, du champ ou du message). Sur un dépôt Odoo, 98 des 209 fichiers ajoutés par `scope-add` étaient des tests, et 5 ajouts ne corrigeaient que des commentaires. Laisse dehors la configuration des scanners et de la suite : un patch ne doit pas pouvoir assouplir ce qui le juge. Sauf si la changer est le but de la tâche : la fiche le dit alors, pour que la relecture le lise.
- Découpe au-delà du seuil que fixe `AGENTS.md` ; à défaut, au-delà d'environ 600 lignes changées, la mesure que suit la routine des vingt tâches. Découpe aussi quand les critères se séparent en comportements livrables seuls. Un gros diff se relit moins bien, et au-delà d'un million de caractères codex refuse la revue. Une tâche par morceau, dans l'ordre des dépendances : la fiche cadre la première et nomme les suivantes.
- Une correction dont le code vit aussi sur une autre branche maintenue du dépôt (par exemple `main` et `20.0`) : cadre sa tâche jumelle dans le même message, sa commande `start` avec `--base '<cette branche>'` (sans lui, la tâche part de la base de `dev-ai.json` ou de la branche courante), ou dis pourquoi le défaut n'y est pas. Sur un dépôt Odoo, 14 des 89 `Fixes-task` portaient un défaut déjà corrigé sur l'autre branche.
- Slug : minuscules, chiffres, `.`, `_` ou `-`, 64 caractères au plus, commençant par une lettre ou un chiffre.

## 5. La spec, là où elle paie

Les prises les plus sérieuses de la relecture croisée ont été des violations d'invariants déclarés : sans spec, le relecteur ne sait pas ce qui doit rester vrai. Propose une spec quand la tâche touche :

- les droits : ACL, règles d'enregistrement, `sudo()`, groupes, multi-société ;
- l'argent : comptabilité, taxes, arrondis, paiements, valorisation de stock ;
- les données persistantes : migrations, schéma, suppressions, imports de masse, champs stockés recalculés ;
- les effets externes : emails, appels d'API, paiements, crons, tout ce qui ne se rejoue pas sans dégât ;
- une API publique ou un contrat entre modules.

Ailleurs, pas de spec, sauf si le projet la demande. Elle tient en 80 lignes au plus, `dev-ai start` refuse au-delà : invariants, préconditions et postconditions, ce qui ne doit pas changer, décisions déjà prises. Pas de plan. Écris-la dans le checkout principal, jamais dans le worktree d'une tâche, sous `.dev-ai/frames/<slug>-spec.md` : `dev-ai init` exclut `.dev-ai/` de git, et le brouillon reste dans le dépôt. Passe son chemin absolu à `--spec` : `start` résout un chemin relatif depuis le dossier où il est lancé, puis recopie la spec avec la tâche.

**Relis le but, et la spec s'il y en a une, contre le code avant de rendre la fiche.** `start` les fige, et le relecteur les lit au mot près, sans la conversation qui les a fait naître : un mot faux ne se corrige qu'en relançant la tâche, après des cycles de relecture perdus. Lis une fois chaque phrase du but, chaque invariant, décision et cas de la spec contre le code, et corrige tout en une passe :

- un mot plus large ou plus étroit que ce que fait le code : marocaine ou non, lot ou alerte, préremplir ou envoyer, vide ou absent. « Adresse sans ville », sans « marocaine », a coûté deux cycles au rappel ONSSA ;
- une propriété que le code n'a pas : un champ que la spec utilise comme mesure, filtre ou regroupement doit être stocké ;
- un mécanisme et une borne qu'il ne tient pas : vérifie le mécanisme dans sa documentation, et n'écris comme contrat que l'un des deux, sauf si l'un découle de l'autre ;
- un comportement existant que la spec tait : écris-le ;
- un fait sur les données (groupes d'un utilisateur, sociétés, paramètres, enregistrements existants) : lis-le sur une copie de la base réelle avant de rendre la commande `start`. Sans copie accessible, pose-le à l'opérateur parmi ses décisions (section 6) : la fiche ne part pas sur un fait non lu. Un test d'acceptation reposait sur les groupes des chefs de projet tels que la spec les décrivait, faux sur la copie de la base réelle : la tâche a été relue sur un fait que la base démentait.

## 6. Les décisions de l'opérateur, en un seul message

Ne pose que ce qui est à lui, et seulement ce que la demande ne tranche pas déjà :

1. Si les critères ou la spec vont au-delà de ce qu'il a dit : représentent-ils le besoin métier ? Toi, tu ne peux pas le savoir.
2. Le mandat : `merge` seulement s'il le dit, dans ses mots ; sinon `commit`, et il merge lui-même.
3. Le découpage, s'il y en a un.
4. Pour un dépôt client dont `AGENTS.md` ne règle pas la question : son contrat autorise-t-il l'envoi du code à un second fournisseur pour la relecture ?

Pose-les sous la fiche en brouillon, dans le même message. Après ses réponses, rends la fiche finale. Sans question à poser, rends-la directement. Sans réponse sur le mandat, c'est `commit`.

## 7. La fiche

Rends ce gabarit, chaque ligne remplie :

```
Tâche      <slug>
Source     besoin | Fixes-task: <slug d'origine> | finding hors du but de <tâche>
Nature     produit | preuve et outillage
But        <ce que « fini » veut dire, en une phrase>
Critères   1. <comportement> → test : <ce qu'il affirme>          garanti
           2. <comportement> → recette : <ce que l'opérateur vérifie>
Périmètre  <paths>
Mandat     merge | commit
Spec       <chemin absolu> | aucune : <pourquoi>
Découpage  <tâches suivantes, dans l'ordre> | aucun
Après le merge, à ta charge : <recette, migration sur copie de prod, déploiement>
```

But et critères s'écrivent dans la langue du dépôt, celle de ses commits : le but devient le message du merge, `merge dev-ai/<slug>: <but>`.

Puis la commande, que `/dev-ai` lancera :

```
dev-ai start <slug> --goal "<but>" --paths '<chemin>' ['<chemin>'…] --author <harness> --author-model <modèle> --delivery <mandat> [--spec '<chemin absolu>'] [--base '<branche>']
```

Le but passe entre guillemets doubles : il ne contient ni backtick, ni `$`, ni `\`, ni `"`, ni `!`, que le shell y exécuterait ou interpréterait. Nomme le code en clair ou entre apostrophes. Chaque chemin, de `--paths` comme de `--spec`, et la branche de `--base` vont entre apostrophes : un espace ne le coupe pas, et dev-ai reçoit un motif glob tel quel, non les fichiers qu'il désigne aujourd'hui.

`--author` et `--author-model` sont ceux de la session qui écrira le patch, pas les tiens : laisse-les en `<…>`, `/dev-ai` les remplit.

« Nature » existe parce qu'une dérive a été mesurée sur un dépôt Odoo : bien plus de tâches de preuve et d'outillage que de code produit. Tu ne la juges pas et tu ne cites aucun chiffre ; tu remplis la ligne, elle rend la dérive visible.

Termine par une ligne : ce que tu as décidé sans qu'on te le demande (seuils, périmètre, découpage), pour que l'opérateur le voie avant de lancer `/dev-ai`.
