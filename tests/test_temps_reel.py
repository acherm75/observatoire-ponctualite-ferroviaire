"""Lecture des flux SIRI Lite à partir d'extraits XML (aucun appel réseau)."""
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

import temps_reel

HORAIRES = """<?xml version="1.0" encoding="UTF-8"?>
<Siri xmlns="http://www.siri.org.uk/siri">
 <ServiceDelivery>
  <ResponseTimestamp>2026-11-09T09:00:00Z</ResponseTimestamp>
  <EstimatedTimetableDelivery><EstimatedJourneyVersionFrame>

   <EstimatedVehicleJourney>
    <ProductCategoryRef>SNCF::highSpeedRail</ProductCategoryRef>
    <PublishedLineName>TGV INOUI</PublishedLineName>
    <DatedVehicleJourneyRef>TGV-6601</DatedVehicleJourneyRef>
    <TrainNumbers><TrainNumberRef>6601</TrainNumberRef></TrainNumbers>
    <OriginName>Paris Gare de Lyon</OriginName>
    <DestinationName>Marseille Saint-Charles</DestinationName>
    <RecordedCalls><RecordedCall>
      <StopPointName>Paris Gare de Lyon</StopPointName><Order>1</Order>
      <AimedDepartureTime>2026-11-09T08:00:00Z</AimedDepartureTime>
      <ExpectedDepartureTime>2026-11-09T08:02:00Z</ExpectedDepartureTime>
      <DeparturePlatformName>K</DeparturePlatformName>
    </RecordedCall></RecordedCalls>
    <EstimatedCalls>
     <EstimatedCall>
      <StopPointName>Lyon Part-Dieu</StopPointName><Order>2</Order>
      <AimedArrivalTime>2026-11-09T10:00:00Z</AimedArrivalTime>
      <ExpectedArrivalTime>2026-11-09T10:04:00Z</ExpectedArrivalTime>
      <Cancellation>true</Cancellation>
     </EstimatedCall>
     <EstimatedCall>
      <StopPointName>Marseille Saint-Charles</StopPointName><Order>3</Order>
      <AimedArrivalTime>2026-11-09T11:20:00Z</AimedArrivalTime>
      <ExpectedArrivalTime>2026-11-09T11:32:00Z</ExpectedArrivalTime>
      <ArrivalPlatformName>B</ArrivalPlatformName>
     </EstimatedCall>
    </EstimatedCalls>
   </EstimatedVehicleJourney>

   <EstimatedVehicleJourney>
    <ProductCategoryRef>SNCF::regionalRail</ProductCategoryRef>
    <FramedVehicleJourneyRef><DatedVehicleJourneyRef>TER-860001</DatedVehicleJourneyRef></FramedVehicleJourneyRef>
    <TrainNumbers><TrainNumberRef>860001</TrainNumberRef></TrainNumbers>
    <OriginName>Rennes</OriginName><DestinationName>Saint-Malo</DestinationName>
    <EstimatedCalls>
     <EstimatedCall><StopPointName>Rennes</StopPointName><Order>1</Order>
      <AimedDepartureTime>2026-11-09T09:10:00Z</AimedDepartureTime>
      <ExpectedDepartureTime>2026-11-09T09:10:00Z</ExpectedDepartureTime></EstimatedCall>
     <EstimatedCall><StopPointName>Saint-Malo</StopPointName><Order>2</Order>
      <AimedArrivalTime>2026-11-09T10:00:00Z</AimedArrivalTime>
      <ExpectedArrivalTime>2026-11-09T10:04:59Z</ExpectedArrivalTime></EstimatedCall>
    </EstimatedCalls>
   </EstimatedVehicleJourney>

   <EstimatedVehicleJourney>
    <ProductCategoryRef>SNCF::metro</ProductCategoryRef>
    <TrainNumbers><TrainNumberRef>4242</TrainNumberRef></TrainNumbers>
    <Cancellation>true</Cancellation>
    <EstimatedCalls>
     <EstimatedCall><StopPointName>Lille Flandres</StopPointName><Order>1</Order>
      <AimedDepartureTime>2026-11-09T09:30:00Z</AimedDepartureTime></EstimatedCall>
     <EstimatedCall><StopPointName>Arras</StopPointName><Order>2</Order>
      <AimedArrivalTime>2026-11-09T10:10:00Z</AimedArrivalTime></EstimatedCall>
    </EstimatedCalls>
   </EstimatedVehicleJourney>

   <EstimatedVehicleJourney>
    <ProductCategoryRef>SNCF::longDistance</ProductCategoryRef>
    <TrainNumbers><TrainNumberRef>3601</TrainNumberRef></TrainNumbers>
   </EstimatedVehicleJourney>

  </EstimatedJourneyVersionFrame></EstimatedTimetableDelivery>
 </ServiceDelivery>
</Siri>"""

PERTURBATIONS = """<?xml version="1.0" encoding="UTF-8"?>
<Siri xmlns="http://www.siri.org.uk/siri"><ServiceDelivery><SituationExchangeDelivery><Situations>
 <PtSituationElement>
  <ValidityPeriod><StartTime>2026-11-01T00:00:00Z</StartTime><EndTime>2026-11-30T00:00:00Z</EndTime></ValidityPeriod>
  <Severity>severe</Severity>
  <Summary xml:lang="EN">Works</Summary>
  <Summary xml:lang="FR">Travaux &amp;eacute;t&amp;eacute;</Summary>
  <Description xml:lang="FR">&lt;p&gt;Trafic   interrompu&lt;br/&gt;entre A et B&lt;/p&gt;</Description>
 </PtSituationElement>
 <PtSituationElement>
  <ValidityPeriod><StartTime>2026-11-01T00:00:00Z</StartTime></ValidityPeriod>
  <Summary xml:lang="FR">Travaux &amp;eacute;t&amp;eacute;</Summary>
  <Description xml:lang="FR">&lt;p&gt;Trafic interrompu entre A et B&lt;/p&gt;</Description>
 </PtSituationElement>
 <PtSituationElement>
  <ValidityPeriod><StartTime>2026-12-01T00:00:00Z</StartTime></ValidityPeriod>
  <Summary>Futur</Summary>
 </PtSituationElement>
 <PtSituationElement>
  <ValidityPeriod><StartTime>2026-10-01T00:00:00Z</StartTime><EndTime>2026-10-31T00:00:00Z</EndTime></ValidityPeriod>
  <Summary>Terminé</Summary>
 </PtSituationElement>
 <PtSituationElement>
  <ValidityPeriod><StartTime>2026-11-01T00:00:00Z</StartTime></ValidityPeriod>
  <Summary>Sans langue</Summary>
 </PtSituationElement>
</Situations></SituationExchangeDelivery></ServiceDelivery></Siri>"""


@pytest.fixture
def flux(monkeypatch):
    contenus = {temps_reel.URL_HORAIRES: HORAIRES, temps_reel.URL_PERTURBATIONS: PERTURBATIONS}
    monkeypatch.setattr(temps_reel, "_telecharger", lambda url: ET.fromstring(contenus[url].encode()))


@pytest.fixture
def trains_arrets(flux):
    return temps_reel.charger_trains()


def test_horodatage_en_heure_de_paris(trains_arrets):
    *_, horodatage = trains_arrets
    assert horodatage == pd.Timestamp("2026-11-09 10:00", tz="Europe/Paris")


def test_un_train_par_trajet_avec_arrets(trains_arrets):
    trains, arrets, _ = trains_arrets
    assert trains["numero"].tolist() == ["6601", "860001", "4242"]  # le 3601 n'a aucun arrêt
    assert trains["categorie"].tolist() == ["TGV", "TER", "Autre"]
    assert len(arrets) == 7


def test_identifiant_du_train(trains_arrets):
    trains, *_ = trains_arrets
    assert trains["id_train"].tolist() == ["TGV-6601", "TER-860001", "4242"]


def test_retard_au_terminus_et_seuil_de_5_minutes(trains_arrets):
    trains, *_ = trains_arrets
    t = trains.set_index("numero")
    assert t.loc["6601", "retard_terminus_min"] == 12
    assert t.loc["860001", "retard_terminus_min"] == pytest.approx(4.983, abs=1e-3)
    assert t["en_retard"].tolist() == [True, False, False]  # 4 min 59 s : à l'heure ; sans estimation : à l'heure


@pytest.mark.parametrize("arrivee_estimee, en_retard", [
    ("10:04:59", False), ("10:05:00", True), ("10:06:00", True), ("09:58:00", False)])
def test_seuil_de_retard_aux_bornes(monkeypatch, arrivee_estimee, en_retard):
    xml = HORAIRES.replace("2026-11-09T10:04:59Z", f"2026-11-09T{arrivee_estimee}Z")
    monkeypatch.setattr(temps_reel, "_telecharger", lambda url: ET.fromstring(xml.encode()))
    trains, *_ = temps_reel.charger_trains()
    assert trains.set_index("numero").loc["860001", "en_retard"] == en_retard


def test_suppressions(trains_arrets):
    trains, arrets, _ = trains_arrets
    t = trains.set_index("numero")
    assert not t.loc["6601", "supprime"] and t.loc["6601", "partiellement_supprime"]
    assert not t.loc["860001", "partiellement_supprime"]
    assert t.loc["4242", "supprime"] and not t.loc["4242", "partiellement_supprime"]
    assert arrets[arrets["numero"] == "4242"]["arret_supprime"].all()


def test_detail_des_arrets(trains_arrets):
    _, arrets, _ = trains_arrets
    tgv = arrets[arrets["numero"] == "6601"].set_index("gare")
    assert tgv["deja_passe"].tolist() == [True, False, False]
    assert tgv.loc["Paris Gare de Lyon", "retard_depart_min"] == 2
    assert tgv.loc["Paris Gare de Lyon", "quai"] == "K"
    assert tgv.loc["Marseille Saint-Charles", "quai"] == "B"
    assert tgv.loc["Lyon Part-Dieu", "arret_supprime"]
    assert tgv.loc["Paris Gare de Lyon", "depart_prevu"] == pd.Timestamp("2026-11-09 09:00", tz="Europe/Paris")


def test_trains_premier_depart_et_derniere_arrivee(trains_arrets):
    trains, *_ = trains_arrets
    tgv = trains.iloc[0]
    assert tgv["depart_prevu"] == pd.Timestamp("2026-11-09 09:00", tz="Europe/Paris")
    assert tgv["arrivee_prevue"] == pd.Timestamp("2026-11-09 12:20", tz="Europe/Paris")


def test_flux_vide(monkeypatch):
    vide = '<Siri xmlns="http://www.siri.org.uk/siri"><ServiceDelivery/></Siri>'
    monkeypatch.setattr(temps_reel, "_telecharger", lambda url: ET.fromstring(vide))
    trains, arrets, horodatage = temps_reel.charger_trains()
    assert trains.empty and arrets.empty and horodatage is None


def test_perturbations_en_cours_seulement(flux, monkeypatch):
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(
        lambda cls, tz=None: pd.Timestamp("2026-11-09 10:00", tz="Europe/Paris")))
    p = temps_reel.charger_perturbations()
    assert sorted(p["resume"]) == ["Sans langue", "Travaux été"]  # futur et terminé écartés


def test_perturbations_texte_francais_sans_html_ni_doublon(flux, monkeypatch):
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(
        lambda cls, tz=None: pd.Timestamp("2026-11-09 10:00", tz="Europe/Paris")))
    p = temps_reel.charger_perturbations().set_index("resume")
    assert p.loc["Travaux été", "description"] == "Trafic interrompu entre A et B"
    assert p.loc["Travaux été", "gravite"] == "severe"


def test_aucune_perturbation(monkeypatch):
    vide = '<Siri xmlns="http://www.siri.org.uk/siri"><ServiceDelivery/></Siri>'
    monkeypatch.setattr(temps_reel, "_telecharger", lambda url: ET.fromstring(vide))
    p = temps_reel.charger_perturbations()
    assert p.empty and list(p.columns) == ["gravite", "resume", "description", "debut", "fin"]
