import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime

# Définir les causes d'arrêts par défaut
types_arret = ['Panne', 'Attente MP', 'Qualité', 'Réglage', 'MO', 'Attente chariot']

# Définir le chemin vers le bureau
desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
db_path = os.path.join(desktop_path, "suivi_jr.db")

# Connexion à la base de données
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

# Création des tables 
def init_db():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS machines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT UNIQUE
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS production (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER,
        date TEXT,
        shift TEXT,
        objectif INTEGER,
        realise INTEGER,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS arrets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        production_id INTEGER,
        type TEXT,
        duree REAL,
        FOREIGN KEY(production_id) REFERENCES production(id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        production_id INTEGER,
        commentaire TEXT,
        FOREIGN KEY(production_id) REFERENCES production(id)
    )''')

    # Machines par défaut
    machines = ['CTL 1250', 'CTL 1600', 'CTL 12', 'PBM 120']
    for machine in machines:
        cursor.execute("INSERT OR IGNORE INTO machines(nom) VALUES (?)", (machine,))
    conn.commit()

init_db()

# Récupération machines
machines_df = pd.read_sql("SELECT * FROM machines", conn)

# Menu de navigation
menu = st.sidebar.selectbox("Menu", ["Dashboard", "Historique", "Rapport"])

if menu == "Dashboard":
    st.title("📊 Dashboard Suivi de Production")

    date_selected = st.date_input("📅 Date", datetime.today())
    shift_selected = st.selectbox("🕐 Shift", ["matin", "après-midi", "nuit"])

    # Section pour ajouter de nouvelles machines
    st.header("➕ Ajouter une nouvelle machine")
    new_machine = st.text_input("Nom de la nouvelle machine")
    if st.button("Ajouter la machine"):
        if new_machine.strip():
            try:
                cursor.execute("INSERT INTO machines(nom) VALUES (?)", (new_machine.strip(),))
                conn.commit()
                st.success(f"✅ Machine '{new_machine}' ajoutée avec succès.")
            except sqlite3.IntegrityError:
                st.error(f"⚠️ La machine '{new_machine}' existe déjà.")
        else:
            st.error("⚠️ Le nom de la machine ne peut pas être vide.")

    # Section pour ajouter de nouvelles causes d'arrêts
    st.header("➕ Ajouter une nouvelle cause d'arrêt")
    new_cause = st.text_input("Nom de la nouvelle cause d'arrêt")
    if st.button("Ajouter la cause d'arrêt"):
        if new_cause.strip():
            # Ajouter la nouvelle cause à la liste des types d'arrêts
            types_arret.append(new_cause.strip())
            st.success(f"✅ Cause d'arrêt '{new_cause}' ajoutée avec succès.")
        else:
            st.error("⚠️ Le nom de la cause d'arrêt ne peut pas être vide.")

    # Saisie / modification des données de production
    st.header("🛠️ Mise à jour des données")

    for idx, row in machines_df.iterrows():
        st.subheader(f"🔧 {row['nom']}")
        objectif = st.number_input(f"🎯 Objectif ({row['nom']})", min_value=0, key=f"obj_{row['id']}")
        realise = st.number_input(f"✅ Réalisé ({row['nom']})", min_value=0, key=f"real_{row['id']}")

        # Insertion ou mise à jour de la production
        cursor.execute("SELECT id FROM production WHERE machine_id=? AND date=? AND shift=?", 
                    (row['id'], date_selected.isoformat(), shift_selected))
        prod = cursor.fetchone()

        if prod:
            cursor.execute("UPDATE production SET objectif=?, realise=? WHERE id=?", 
                        (objectif, realise, prod[0]))
            prod_id = prod[0]
        else:
            cursor.execute("INSERT INTO production(machine_id, date, shift, objectif, realise) VALUES (?,?,?,?,?)",
                        (row['id'], date_selected.isoformat(), shift_selected, objectif, realise))
            prod_id = cursor.lastrowid
        conn.commit()

        # Saisie des arrêts
        st.markdown("⛔ **Arrêts (en heures)**")
        for type_arret in types_arret:
            duree = st.number_input(f"{type_arret} ({row['nom']})", min_value=0.0, step=0.5, key=f"{type_arret}_{row['id']}")
            # Supprimer l'ancien
            cursor.execute("DELETE FROM arrets WHERE production_id=? AND type=?", (prod_id, type_arret))
            if duree > 0:
                cursor.execute("INSERT INTO arrets(production_id, type, duree) VALUES (?,?,?)", (prod_id, type_arret, duree))
        conn.commit()

        # Observation
        observation = st.text_input(f"📝 Observation ({row['nom']})", key=f"obs_{row['id']}")
        cursor.execute("DELETE FROM observations WHERE production_id=?", (prod_id,))
        if observation.strip():
            cursor.execute("INSERT INTO observations(production_id, commentaire) VALUES (?, ?)", (prod_id, observation))
        conn.commit()

    st.success("✅ Données enregistrées avec succès.")

    # Affichage du tableau de suivi
    st.header("📋 Résumé du suivi de production")

    query = """
    SELECT m.nom AS Machine,
        p.objectif AS Objectif,
        p.realise AS Réalisé,
        ROUND(CAST(p.realise AS FLOAT) / NULLIF(p.objectif, 0) * 100, 1) AS '% Réalisation',
        COALESCE(GROUP_CONCAT(a.type || ': ' || a.duree || 'h', ' / '), '-') AS Arrêts,
        COALESCE(o.commentaire, '-') AS Observation
    FROM production p
    JOIN machines m ON p.machine_id = m.id
    LEFT JOIN arrets a ON a.production_id = p.id
    LEFT JOIN observations o ON o.production_id = p.id
    WHERE p.date = ? AND p.shift = ?
    GROUP BY p.id
    ORDER BY m.nom;
    """

    df = pd.read_sql_query(query, conn, params=(date_selected.isoformat(), shift_selected))
    st.dataframe(df)

    # Section pour filtrer les données par plage de dates
    st.header("📅 Filtrer les données par plage de dates")
    start_date = st.date_input("Date de début", datetime.today())
    end_date = st.date_input("Date de fin", datetime.today())

    if start_date > end_date:
        st.error("⚠️ La date de début doit être antérieure ou égale à la date de fin.")
    else:
        query = """
        SELECT m.nom AS Machine,
            p.date AS Date,
            p.shift AS Shift,
            p.objectif AS Objectif,
            p.realise AS Réalisé,
            ROUND(CAST(p.realise AS FLOAT) / NULLIF(p.objectif, 0) * 100, 1) AS '% Réalisation',
            COALESCE(GROUP_CONCAT(a.type || ': ' || a.duree || 'h', ' / '), '-') AS Arrêts,
            COALESCE(o.commentaire, '-') AS Observation
        FROM production p
        JOIN machines m ON p.machine_id = m.id
        LEFT JOIN arrets a ON a.production_id = p.id
        LEFT JOIN observations o ON o.production_id = p.id
        WHERE p.date BETWEEN ? AND ?
        GROUP BY p.id
        ORDER BY p.date, m.nom;
        """
        filtered_df = pd.read_sql_query(query, conn, params=(start_date.isoformat(), end_date.isoformat()))
        st.dataframe(filtered_df)

    # Graphique 
    if not df.empty:
        st.subheader("📈 Taux de Réalisation")
        st.bar_chart(df.set_index("Machine")["% Réalisation"])

elif menu == "Historique":
    st.title("📜 Historique")
    # Filtres pour l'historique
    machine_filter = st.selectbox("Filtrer par machine", ["Toutes"] + machines_df['nom'].tolist())
    shift_filter = st.selectbox("Filtrer par shift", ["Tous", "matin", "après-midi", "nuit"])
    date_filter = st.date_input("Filtrer par date", datetime.today())

    # Construire la requête SQL avec les filtres
    query = """
    SELECT m.nom AS Machine,
        p.date AS Date,
        p.shift AS Shift,
        p.objectif AS Objectif,
        p.realise AS Réalisé,
        ROUND(CAST(p.realise AS FLOAT) / NULLIF(p.objectif, 0) * 100, 1) AS '% Réalisation',
        COALESCE(GROUP_CONCAT(a.type || ': ' || a.duree || 'h', ' / '), '-') AS Arrêts,
        COALESCE(o.commentaire, '-') AS Observation
    FROM production p
    JOIN machines m ON p.machine_id = m.id
    LEFT JOIN arrets a ON a.production_id = p.id
    LEFT JOIN observations o ON o.production_id = p.id
    WHERE (? = 'Toutes' OR m.nom = ?)
    AND (? = 'Tous' OR p.shift = ?)
    AND p.date = ?
    GROUP BY p.id
    ORDER BY p.date, m.nom;
    """
    history_df = pd.read_sql_query(query, conn, params=(machine_filter, machine_filter, shift_filter, shift_filter, date_filter.isoformat()))
    st.dataframe(history_df)

elif menu == "Rapport":
    st.title("📄 Rapport")
    
    # Filtres pour le rapport
    start_date = st.date_input("Date de début", datetime.today())
    end_date = st.date_input("Date de fin", datetime.today())
    machine_filter = st.selectbox("Filtrer par machine", ["Toutes"] + machines_df['nom'].tolist())

    if start_date > end_date:
        st.error("⚠️ La date de début doit être antérieure ou égale à la date de fin.")
    else:
        # Tableau des arrêts
        st.subheader("⛔ Tableau des Arrêts")
        query_arrets = """
        SELECT a.type AS Type_Arret,
               SUM(a.duree) AS Total_Heures,
               GROUP_CONCAT(o.commentaire, ' / ') AS Observations
        FROM arrets a
        LEFT JOIN production p ON a.production_id = p.id
        LEFT JOIN observations o ON o.production_id = p.id
        LEFT JOIN machines m ON p.machine_id = m.id
        WHERE p.date BETWEEN ? AND ?
          AND (? = 'Toutes' OR m.nom = ?)
        GROUP BY a.type
        ORDER BY Total_Heures DESC;
        """
        arrets_df = pd.read_sql_query(query_arrets, conn, params=(start_date.isoformat(), end_date.isoformat(), machine_filter, machine_filter))
        st.dataframe(arrets_df)

        # Tableau principal
        st.subheader("📋 Tableau Principal")
        query = """
        SELECT m.nom AS Machine,
               p.date AS Date,
               p.shift AS Shift,
               p.objectif AS Objectif,
               p.realise AS Réalisé,
               ROUND(CAST(p.realise AS FLOAT) / NULLIF(p.objectif, 0) * 100, 1) AS '% Réalisation',
               COALESCE(GROUP_CONCAT(a.type || ': ' || a.duree || 'h', ' / '), '-') AS Arrêts,
               COALESCE(o.commentaire, '-') AS Observation
        FROM production p
        JOIN machines m ON p.machine_id = m.id
        LEFT JOIN arrets a ON a.production_id = p.id
        LEFT JOIN observations o ON o.production_id = p.id
        WHERE p.date BETWEEN ? AND ?
          AND (? = 'Toutes' OR m.nom = ?)
        GROUP BY p.id
        ORDER BY p.date, m.nom;
        """
        report_df = pd.read_sql_query(query, conn, params=(start_date.isoformat(), end_date.isoformat(), machine_filter, machine_filter))

        # Ajouter une ligne de total
        if not report_df.empty:
            total_row = {
                "Machine": "Total",
                "Date": "-",
                "Shift": "-",
                "Objectif": report_df["Objectif"].sum(),
                "Réalisé": report_df["Réalisé"].sum(),
                "% Réalisation": round(report_df["Réalisé"].sum() / report_df["Objectif"].sum() * 100, 1) if report_df["Objectif"].sum() > 0 else 0,
                "Arrêts": "-",
                "Observation": "-"
            }
            report_df = pd.concat([report_df, pd.DataFrame([total_row])], ignore_index=True)

        st.dataframe(report_df)
