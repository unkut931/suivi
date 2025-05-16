import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime
import plotly.express as px
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(
    page_title="Suivi de Production",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
        .main {background-color: #f5f5f5;}
        h1 {color: #2a5885;}
        h2 {color: #3a7ca5;}
        .st-bq {border-left: 5px solid #3a7ca5;}
        .stButton>button {background-color: #3a7ca5; color: white;}
        .stNumberInput>div>div>input {background-color: #f0f2f6;}
    </style>
""", unsafe_allow_html=True)

# Définir les causes d'arrêts par défaut
types_arret = ['Panne', 'Attente MP', 'Qualité', 'Réglage', 'MO', 'Attente chariot']

# Définir le chemin vers la base de données
db_path = "suivi_jr.db"

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

    # Filtres en colonnes
    col1, col2 = st.columns(2)
    with col1:
        date_selected = st.date_input("📅 Date", datetime.today())
    with col2:
        shift_selected = st.selectbox("🕐 Shift", ["matin", "après-midi", "nuit"])

    # Onglets pour chaque machine
    st.header("Machines")
    tabs = st.tabs([f"🔧 {row['nom']}" for idx, row in machines_df.iterrows()])
    for idx, (tab, (_, row)) in enumerate(zip(tabs, machines_df.iterrows())):
        with tab:
            col_obj, col_real, col_perc = st.columns(3)
            cursor.execute("SELECT id FROM production WHERE machine_id=? AND date=? AND shift=?", 
                        (row['id'], date_selected.isoformat(), shift_selected))
            prod = cursor.fetchone()
            with col_obj:
                objectif = st.number_input(f"🎯 Objectif", min_value=0, key=f"obj_{row['id']}")
            with col_real:
                realise = st.number_input(f"✅ Réalisé", min_value=0, key=f"real_{row['id']}")
            with col_perc:
                perc = (realise / objectif) * 100 if objectif > 0 else 0
                st.metric("% Réalisation", f"{perc:.1f}%" if objectif > 0 else "N/A")
            
            # Mise à jour base
            if prod:
                cursor.execute("UPDATE production SET objectif=?, realise=? WHERE id=?", 
                            (objectif, realise, prod[0]))
                prod_id = prod[0]
            else:
                cursor.execute("INSERT INTO production(machine_id, date, shift, objectif, realise) VALUES (?,?,?,?,?)",
                            (row['id'], date_selected.isoformat(), shift_selected, objectif, realise))
                prod_id = cursor.lastrowid
            conn.commit()
            
            # Arrêts
            with st.expander("⛔ Arrêts (en heures)"):
                cols = st.columns(2)
                for i, type_arret in enumerate(types_arret):
                    with cols[i % 2]:
                        duree = st.number_input(f"{type_arret}", min_value=0.0, step=0.5, key=f"{type_arret}_{row['id']}")
                        cursor.execute("DELETE FROM arrets WHERE production_id=? AND type=?", (prod_id, type_arret))
                        if duree > 0:
                            cursor.execute("INSERT INTO arrets(production_id, type, duree) VALUES (?,?,?)", (prod_id, type_arret, duree))
                conn.commit()
            
            # Observation
            observation = st.text_area(f"📝 Observation", key=f"obs_{row['id']}")
            cursor.execute("DELETE FROM observations WHERE production_id=?", (prod_id,))
            if observation.strip():
                cursor.execute("INSERT INTO observations(production_id, commentaire) VALUES (?, ?)", (prod_id, observation))
            conn.commit()

    # Résumé et KPIs
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

    # KPIs
    total_objectif = df['Objectif'].sum()
    total_realise = df['Réalisé'].sum()
    perc_total = (total_realise / total_objectif * 100) if total_objectif > 0 else 0
    k1, k2, k3 = st.columns(3)
    k1.metric("🎯 Objectif Total", f"{total_objectif:,}")
    k2.metric("✅ Réalisé Total", f"{total_realise:,}")
    k3.metric("📊 % Réalisation", f"{perc_total:.1f}%", delta=f"{(perc_total - 100):.1f}%" if total_objectif > 0 else "N/A")

elif menu == "Historique":
    st.title("📜 Historique")
    with st.expander("🔎 Filtres", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            machine_filter = st.selectbox("Machine", ["Toutes"] + machines_df['nom'].tolist(), key="hist_machine")
        with col2:
            shift_filter = st.selectbox("Shift", ["Tous", "matin", "après-midi", "nuit"], key="hist_shift")
        with col3:
            date_filter = st.date_input("Date", datetime.today(), key="hist_date")

    # Requête SQL modifiée pour formater les dates
    query_hist = """
    SELECT 
        m.nom AS Machine,
        strftime('%Y-%m-%d', p.date) AS Date,
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
      AND date(p.date) = date(?)
    GROUP BY p.id
    ORDER BY p.date, m.nom;
    """
    
    history_df = pd.read_sql_query(
        query_hist, conn,
        params=(machine_filter, machine_filter, shift_filter, shift_filter, date_filter.isoformat())
    )

    # Conversion des types de données
    history_df['Date'] = history_df['Date'].astype(str)
    
    st.subheader("Données Historiques")
    
    # Solution avec st.data_editor (recommandé)
    edited_df = st.data_editor(
        history_df,
        key="history_editor",
        num_rows="fixed",
        use_container_width=True,
        disabled=["Machine", "Date", "Shift"]  # Colonnes non modifiables
    )
    
    # Gestion de la sélection et suppression
    if st.button("🗑️ Supprimer la ligne sélectionnée"):
        if len(edited_df) > 0:
            selected_indices = st.session_state.get("history_editor", {}).get("edited_rows", {}).keys()
            if selected_indices:
                selected_row = history_df.iloc[list(selected_indices)[0]]
                cursor.execute(
                    "DELETE FROM production WHERE machine_id = (SELECT id FROM machines WHERE nom = ?) AND date = ? AND shift = ?",
                    (selected_row['Machine'], selected_row['Date'], selected_row['Shift'])
                )
                conn.commit()
                st.success("Ligne supprimée avec succès")
                st.rerun()
            else:
                st.warning("Veuillez sélectionner une ligne à supprimer")
        else:
            st.warning("Aucune donnée disponible")

elif menu == "Rapport":
    st.title("📄 Rapport")
    with st.expander("🔎 Filtres", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Date de début", datetime.today())
            end_date = st.date_input("Date de fin", datetime.today())
        with col2:
            machine_filter = st.selectbox("Machine", ["Toutes"] + machines_df['nom'].tolist())
    
    if start_date > end_date:
        st.error("⚠️ La date de début doit être antérieure ou égale à la date de fin.")
    else:
        # Analyse des Arrêts
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
        arrets_df = pd.read_sql_query(
            query_arrets, conn,
            params=(start_date.isoformat(), end_date.isoformat(), machine_filter, machine_filter)
        )

        st.subheader("⛔ Analyse des Arrêts")
        tab1, tab2 = st.tabs(["Tableau", "Graphique"])
        with tab1:
            st.dataframe(arrets_df)
        with tab2:
            if not arrets_df.empty:
                fig = px.pie(arrets_df, values='Total_Heures', names='Type_Arret',
                             title="Répartition des temps d'arrêt")
                st.plotly_chart(fig, use_container_width=True)
        
        # Synthèse de Production
        st.subheader("📋 Synthèse de Production")
        query_report = """
        SELECT 
            m.nom AS Machine,
            p.date AS Date,
            SUM(p.objectif) AS Objectif,
            SUM(p.realise) AS Réalisé
        FROM production p
        JOIN machines m ON p.machine_id = m.id
        WHERE p.date BETWEEN ? AND ?
          AND (? = 'Toutes' OR m.nom = ?)
        GROUP BY m.nom, p.date
        ORDER BY p.date, m.nom;
        """
        report_df = pd.read_sql_query(
            query_report, conn,
            params=(start_date.isoformat(), end_date.isoformat(), machine_filter, machine_filter)
        )

        # Calcul du % Réalisation
        report_df["% Réalisation"] = report_df.apply(
            lambda row: round((row["Réalisé"] / row["Objectif"] * 100), 1) if row["Objectif"] > 0 else 0, axis=1
        )
        report_df["% Réalisation"] = report_df["% Réalisation"].astype(str) + " %"

        st.dataframe(report_df)

        # Analyses Avancées
        st.header("📊 Analyses Avancées")
        tab1, tab2, tab3 = st.tabs(["Évolution Temporelle", "Heatmap des Arrêts", "Comparaison Shifts"])

        with tab1:
            query_evolution = """
            SELECT p.date AS Date,
                   AVG(CASE WHEN p.objectif > 0 THEN (CAST(p.realise AS FLOAT) / p.objectif) * 100 ELSE NULL END) AS Taux_Realisation
            FROM production p
            JOIN machines m ON p.machine_id = m.id
            WHERE p.date BETWEEN ? AND ?
              AND (? = 'Toutes' OR m.nom = ?)
            GROUP BY p.date
            ORDER BY p.date;
            """
            evolution_df = pd.read_sql_query(query_evolution, conn, 
                                           params=(start_date.isoformat(), end_date.isoformat(), 
                                                  machine_filter, machine_filter))

            if not evolution_df.empty:
                fig = px.line(evolution_df, x='Date', y='Taux_Realisation',
                             title="Évolution quotidienne du taux de réalisation",
                             markers=True)
                fig.update_yaxes(title_text="Taux de réalisation (%)")
                fig.update_traces(line_color='#3a7ca5', line_width=2)
                fig.add_hline(y=100, line_dash="dash", line_color="red")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Aucune donnée disponible pour la période sélectionnée")

        with tab2:
            query_heatmap = """
            SELECT m.nom AS Machine, 
                   a.type AS Type_Arret,
                   SUM(a.duree) AS Duree_Totale
            FROM arrets a
            JOIN production p ON a.production_id = p.id
            JOIN machines m ON p.machine_id = m.id
            WHERE p.date BETWEEN ? AND ?
              AND (? = 'Toutes' OR m.nom = ?)
            GROUP BY m.nom, a.type
            ORDER BY Duree_Totale DESC;
            """
            heatmap_df = pd.read_sql_query(query_heatmap, conn,
                                         params=(start_date.isoformat(), end_date.isoformat(),
                                                machine_filter, machine_filter))

            if not heatmap_df.empty:
                pivot_df = heatmap_df.pivot(index="Machine", columns="Type_Arret", values="Duree_Totale").fillna(0)
                fig = px.imshow(pivot_df,
                               labels=dict(x="Type d'arrêt", y="Machine", color="Heures"),
                               color_continuous_scale='YlOrRd',
                               title="Durée des arrêts par machine et par type")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Aucun arrêt enregistré pour la période sélectionnée")

        with tab3:
            query_shifts = """
            SELECT p.shift AS Shift,
                   AVG(CASE WHEN p.objectif > 0 THEN (CAST(p.realise AS FLOAT) / p.objectif) * 100 ELSE NULL END) AS Taux_Realisation,
                   SUM(a.duree) AS Total_Arrets
            FROM production p
            LEFT JOIN arrets a ON a.production_id = p.id
            JOIN machines m ON p.machine_id = m.id
            WHERE p.date BETWEEN ? AND ?
              AND (? = 'Toutes' OR m.nom = ?)
            GROUP BY p.shift
            ORDER BY p.shift;
            """
            shifts_df = pd.read_sql_query(query_shifts, conn,
                                        params=(start_date.isoformat(), end_date.isoformat(),
                                              machine_filter, machine_filter))

            if not shifts_df.empty:
                shifts_df["Taux_Realisation"] = shifts_df["Taux_Realisation"].fillna(0).astype(int)
                col1, col2 = st.columns(2)
                with col1:
                    fig = px.bar(
                        shifts_df, x='Shift', y='Taux_Realisation',
                        title="Performance par Shift",
                        text=shifts_df["Taux_Realisation"].astype(str) + " %",
                        color='Shift'
                    )
                    fig.update_yaxes(title_text="Taux de réalisation (%)")
                    fig.update_traces(texttemplate='%{text}', textposition='outside')
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    fig = px.bar(
                        shifts_df, x='Shift', y='Total_Arrets',
                        title="Temps d'arrêt par Shift",
                        text=shifts_df["Total_Arrets"].fillna(0).astype(int),
                        color='Shift'
                    )
                    fig.update_yaxes(title_text="Heures d'arrêt")
                    fig.update_traces(texttemplate='%{text}', textposition='outside')
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Aucune donnée disponible pour comparer les shifts")
