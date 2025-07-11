# Test to verify database integrity
# database object 'db' defined in conftest.py
import pytest
from astrodbkit.astrodb import or_
from astropy import units as u
from astropy.table import unique
from sqlalchemy import and_, func


def test_reference_uniqueness(db):
    # Verify that all Publications.name values are unique
    t = db.query(db.Publications.c.reference).astropy()
    assert len(t) == len(unique(t, keys="reference")), "duplicated publications found"

    # Verify that DOI are supplied
    t = (
        db.query(db.Publications.c.reference)
        .filter(db.Publications.c.doi.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print(f"\n{len(t)} publications lacking DOI:")
        print(t)

    # Verify that Bibcodes are supplied
    t = (
        db.query(db.Publications.c.reference)
        .filter(db.Publications.c.bibcode.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print(f"\n{len(t)} publications lacking ADS bibcodes:")
        print(t)


def test_references(db):
    # Verify that all data point to an existing Publication

    ref_list = []
    table_list = ["Sources", "Photometry", "Parallaxes", "ProperMotions", "Spectra"]
    for table in table_list:
        # Get list of unique references
        t = db.query(db.metadata.tables[table].c.reference).distinct().astropy()
        ref_list = ref_list + t["reference"].tolist()

    # Getting unique set
    ref_list = list(set(ref_list))

    # Confirm that all are in Publications
    t = (
        db.query(db.Publications.c.reference)
        .filter(db.Publications.c.reference.in_(ref_list))
        .astropy()
    )
    assert len(t) == len(ref_list), "Some references were not matched"

    # List out publications that have not been used
    t = (
        db.query(db.Publications.c.reference)
        .filter(db.Publications.c.reference.notin_(ref_list))
        .astropy()
    )
    assert len(t) <= 606, f"{len(t)} unused references"


def test_publications(db):
    # Find unused references in the Sources Table
    # stm = except_(select([db.Publications.c.reference]),
    # select([db.Sources.c.reference]))
    # result = db.session.execute(stm)
    # s = result.scalars().all()
    # assert len(s) == 720, f'found {len(s)} unused references'

    # Find references with no doi or bibcode
    t = (
        db.query(db.Publications.c.reference)
        .filter(
            or_(
                and_(
                    db.Publications.c.doi.is_(None), db.Publications.c.bibcode.is_(None)
                ),
                and_(
                    db.Publications.c.doi.is_(""), db.Publications.c.bibcode.is_(None)
                ),
                and_(
                    db.Publications.c.doi.is_(None), db.Publications.c.bibcode.is_("")
                ),
                and_(db.Publications.c.doi.is_(""), db.Publications.c.bibcode.is_("")),
            )
        )
        .astropy()
    )
    assert len(t) == 31, f"found {len(t)} publications with missing bibcode and doi"


def test_parameters(db):
    """
    Test the Parameters table exists and has data
    """

    t = db.query(db.Parameters).astropy()
    assert len(t) > 0, "Parameters table is empty"

    # Check usage of Parameters
    param_list = db.query(db.ModeledParameters.c.parameter).astropy()
    if len(param_list) > 0:
        # Get unique values
        param_list = list(param_list["parameter"])
        param_list = list(set(param_list))
        t = (
            db.query(db.Parameters)
            .filter(db.Parameters.c.parameter.notin_(param_list))
            .astropy()
        )
        if len(t) > 0:
            print("The following parameters are not being used:")
            print(t)
        # Skipping actual assertion test
        # assert len(t) == 0, f'{len(t)} unused parameters'


def test_coordinates(db):
    # Verify that all sources have valid coordinates
    t = (
        db.query(db.Sources.c.source, db.Sources.c.ra, db.Sources.c.dec)
        .filter(
            or_(
                db.Sources.c.ra.is_(None),
                db.Sources.c.ra < 0,
                db.Sources.c.ra > 360,
                db.Sources.c.dec.is_(None),
                db.Sources.c.dec < -90,
                db.Sources.c.dec > 90,
            )
        )
        .astropy()
    )

    if len(t) > 0:
        print(f"\n{len(t)} Sources failed coordinate checks")
        print(t)

    assert len(t) == 0, f"{len(t)} Sources failed coordinate checks"


def test_source_names(db):
    # Verify that all sources have at least one entry in Names table
    sql_text = (
        "SELECT Sources.source	FROM Sources LEFT JOIN Names "
        "ON Names.source=Sources.source WHERE Names.source IS NULL"
    )
    missing_names = db.sql_query(sql_text, fmt="astropy")
    assert len(missing_names) == 0


def test_source_uniqueness(db):
    # Verify that all Sources.source values are unique
    source_names = db.query(db.Sources.c.source).astropy()
    unique_source_names = unique(source_names)
    assert len(source_names) == len(unique_source_names)

    # Another method to find the duplicates
    sql_text = (
        "SELECT Sources.source FROM Sources GROUP BY source " "HAVING (Count(*) > 1)"
    )
    duplicate_names = db.sql_query(sql_text, fmt="astropy")

    # if duplicate_names is non_zero, print out duplicate names
    if len(duplicate_names) > 0:
        print(f"\n{len(duplicate_names)} duplicated names")
        print(duplicate_names)

    assert len(duplicate_names) == 0


def test_names_table(db):
    # Verify that all Sources contain at least one entry in the Names table
    name_list = db.query(db.Sources.c.source).astropy()
    name_list = name_list["source"].tolist()
    source_name_counts = (
        db.query(db.Names.c.source)
        .filter(db.Names.c.source.in_(name_list))
        .distinct()
        .count()
    )
    assert (
        len(name_list) == source_name_counts
    ), "ERROR: There are Sources without entries in the Names table"

    # Verify that each Source contains an entry in
    # Names with Names.source = Names.other_source
    valid_name_counts = (
        db.query(db.Names.c.source)
        .filter(db.Names.c.source == db.Names.c.other_name)
        .distinct()
        .count()
    )

    # If the number of valid names don't match the number of sources,
    # then there are cases that are missing
    # The script below will gather them and print them out
    if len(name_list) != valid_name_counts:
        # Create a temporary table that groups entries in the
        # Names table by their source name
        # with a column containing a concatenation of all known names
        t = (
            db.query(
                db.Names.c.source,
                func.group_concat(db.Names.c.other_name).label("names"),
            )
            .group_by(db.Names.c.source)
            .astropy()
        )

        # Get the list of entries whose source name
        # are not present in the 'other_names' column
        # Then return the Names table results
        # so we can see what the DB has for these entries
        results = [
            row["source"] for row in t if row["source"] not in row["names"].split(",")
        ]
        print("\nEntries in Names without Names.source == Names.other_name:")
        print(db.query(db.Names).filter(db.Names.c.source.in_(results)).astropy())

    assert (
        len(name_list) == valid_name_counts
    ), "ERROR: There are entries in Names without Names.source == Names.other_name"

    # Verify that there are no empty strings as other_names in Names
    blank_names = db.query(db.Names).filter(db.Names.c.other_name == "").astropy()
    assert (
        len(blank_names) == 0
    ), "ERROR: There are entries in Names which are empty strings"


def test_source_uniqueness2(db):
    # Verify that all Sources.source values are unique and find the duplicates
    sql_text = (
        "SELECT Sources.source FROM Sources GROUP BY source " "HAVING (Count(*) > 1)"
    )
    duplicate_names = db.sql_query(sql_text, fmt="astropy")
    # if duplicate_names is non_zero, print out duplicate names
    assert len(duplicate_names) == 0


def test_photometry(db):
    # Tests for Photometry table

    # Check that no negative magnitudes have been provided,
    # nor any that are larger than 99 (if missing/limits, just use None)
    t = (
        db.query(db.Photometry)
        .filter(or_(db.Photometry.c.magnitude < 0, db.Photometry.c.magnitude >= 99))
        .astropy()
    )
    if len(t) > 0:
        print("\nInvalid magnitudes present")
        print(t)
    assert len(t) == 0


def test_photometry_filters(db):
    bands_in_use = db.query(db.Photometry.c.band).distinct().astropy()
    for band_in_use in bands_in_use["band"]:
        check = (
            db.query(db.PhotometryFilters)
            .filter(db.PhotometryFilters.c.band == band_in_use)
            .astropy()
        )
        assert len(check) == 1, f"{band_in_use} not in PhotometryFilters"


def test_parallaxes(db):
    # Tests against the Parallaxes table

    # While there may be many parallax measurements for a single source,
    # there should be only one marked as adopted
    t = (
        db.query(
            db.Parallaxes.c.source,
            func.sum(db.Parallaxes.c.adopted).label("adopted_counts"),
        )
        .group_by(db.Parallaxes.c.source)
        .having(func.sum(db.Parallaxes.c.adopted) > 1)
        .astropy()
    )
    if len(t) > 0:
        print("\nParallax entries with incorrect 'adopted' labels")
        print(t)
    assert len(t) == 0


def test_propermotions(db):
    # Tests against the ProperMotions table

    # There should be no entries in the ProperMotions table without both mu_ra and mu_dec
    t = (
        db.query(db.ProperMotions.c.source)
        .filter(
            or_(db.ProperMotions.c.mu_ra.is_(None), db.ProperMotions.c.mu_dec.is_(None))
        )
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without proper motion values")
        print(t)
    assert len(t) == 0

    # While there may be many proper motion measurements for a single source,
    # there should be only one marked as adopted
    t = (
        db.query(
            db.ProperMotions.c.source,
            func.sum(db.ProperMotions.c.adopted).label("adopted_counts"),
        )
        .group_by(db.ProperMotions.c.source)
        .having(func.sum(db.ProperMotions.c.adopted) > 1)
        .astropy()
    )
    if len(t) > 0:
        print("\nProper Motion measurements with incorrect 'adopted' labels")
        print(t)
    assert len(t) == 0


def test_radialvelocities(db):
    # Tests against the RadialVelocities table

    # There should be no entries in the RadialVelocities table without rv values
    t = (
        db.query(db.RadialVelocities.c.source)
        .filter(db.RadialVelocities.c.radial_velocity_km_s.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without radial velocity values")
        print(t)
    assert len(t) == 0

    # While there may be many radial velocity measurements for a single source,
    # there should be only one marked as adopted
    t = (
        db.query(
            db.RadialVelocities.c.source,
            func.sum(db.RadialVelocities.c.adopted).label("adopted_counts"),
        )
        .group_by(db.RadialVelocities.c.source)
        .having(func.sum(db.RadialVelocities.c.adopted) > 1)
        .astropy()
    )
    if len(t) > 0:
        print("\nRadial velocity measurements with incorrect 'adopted' labels")
        print(t)
    assert len(t) == 0


def test_spectraltypes(db):
    # Tests against the SpectralTypes table

    # There should be no entries in the SpectralTypes table without a spectral type string
    t = (
        db.query(db.SpectralTypes.c.source)
        .filter(db.SpectralTypes.c.spectral_type_string.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without spectral type strings")
        print(t)
    assert len(t) == 0

    # There should be no entries in the SpectralTypes table without a spectral type code
    t = (
        db.query(db.SpectralTypes.c.source)
        .filter(db.SpectralTypes.c.spectral_type_code.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without spectral type codes")
        print(t)
    assert len(t) == 0

    # While there may be many spectral type measurements for a single source,
    # there should be only one marked as adopted
    t = (
        db.query(
            db.SpectralTypes.c.source,
            func.sum(db.SpectralTypes.c.adopted).label("adopted_counts"),
        )
        .group_by(db.SpectralTypes.c.source)
        .having(func.sum(db.SpectralTypes.c.adopted) > 1)
        .astropy()
    )
    if len(t) > 0:
        print("\nSpectral Type entries with incorrect 'adopted' labels")
        print(t)
    assert len(t) == 0


def test_gravities(db):
    # Tests against the Gravities table

    # There should be no entries in the Gravities table without a gravity measurement
    t = (
        db.query(db.Gravities.c.source)
        .filter(db.Gravities.c.gravity.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without gravity values")
        print(t)
    assert len(t) == 0


def test_modeled_parameters(db):
    # There should be no entries in the modeled parameters table without parameter
    t = (
        db.query(db.ModeledParameters)
        .filter(db.ModeledParameters.c.parameter.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without a parameter")
        print(t)
    assert len(t) == 0

    # Test units are astropy.unit resolvable
    t = (
        db.query(db.ModeledParameters)
        .filter(db.ModeledParameters.c.unit.is_not(None))
        .distinct()
        .astropy()
    )
    unit_fail = []
    for x in t:
        unit = x["unit"]
        try:
            assert u.Unit(unit, parse_strict="raise")
        except ValueError:
            print(f"{unit} is not a recognized astropy unit")
            counts = (
                db.query(db.ModeledParameters)
                .filter(db.ModeledParameters.c.unit == unit)
                .count()
            )
            unit_fail.append({unit: counts})  # count of how many of that unit there is

    assert len(unit_fail) == 0, f"Some parameter units did not resolve: {unit_fail}"

    # check no negative Mass, Radius, or Teff
    t = (
        db.query(db.ModeledParameters)
        .filter(
            and_(
                db.ModeledParameters.c.parameter.in_(["radius", "mass", "Teff"]),
                db.ModeledParameters.c.value < 0,
            )
        )
        .astropy()
    )
    if len(t) > 0:
        print("\n Negative value for Radius, Mass, or Teff not allowed.\n")
        print(t)
    assert len(t) == 0

    # check no negative value error
    t = (
        db.query(db.ModeledParameters)
        .filter(
            and_(
                db.ModeledParameters.c.value_error is not None,
                db.ModeledParameters.c.value_error < 0,
            )
        )
        .astropy()
    )

    if len(t) > 0:
        print("\n Negative projected separations")
        print(t)
    assert len(t) == 0


def test_spectra(db):
    # Tests against the Spectra table

    # There should be no entries in the Spectra table without a spectrum
    t = (
        db.query(db.Spectra.c.source)
        .filter(db.Spectra.c.access_url.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\nEntries found without spectrum")
        print(t)
    assert len(t) == 0

    # All spectra should have a unique filename
    sql_text = (
        "SELECT Spectra.access_url, Spectra.source "
        "FROM Spectra "
        "GROUP BY access_url "
        "HAVING (Count(*) > 1)"
    )
    duplicate_spectra = db.sql_query(sql_text, fmt="astropy")

    # if duplicate spectra is non_zero, print out duplicate names
    if len(duplicate_spectra) > 0:
        print(f"\n{len(duplicate_spectra)} duplicated spectra")
        print(duplicate_spectra)
        print(duplicate_spectra["source"])

    assert len(duplicate_spectra) == 22
    # 21 are xshooter spectra which correctly have two entires
    # 1 (W1542%2B22.csv) is an incorrect duplicate and the topic of
    # https://github.com/SIMPLE-AstroDB/SIMPLE-db/issues/442


def test_special_characters(db):
    # This test asserts that no special unicode characters are in the database
    # This can be expanded with additional characters we want to avoid
    bad_characters = [
        "\u2013",
        "\u00f3",
        "\u00e9",
        "\u00ed",
        "\u00e1",
        "\u00fa",
        "\u0000",
    ]
    for char in bad_characters:
        data = db.search_string(char)
        # Make sure primary/foreign keys don't have unicode
        # but not checking comments/descriptions
        if len(data) > 0:
            for table_name in data.keys():
                if table_name == "Publications":
                    check = [char not in data[table_name]["reference"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Spectra":
                    check = [char not in data[table_name]["access_url"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Names":
                    check = [char not in data[table_name]["other_name"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Instruments":
                    check = [char not in data[table_name]["instrument"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Telescopes":
                    check = [char not in data[table_name]["telescope"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Parameters":
                    check = [char not in data[table_name]["parameter"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "PhotometryFilters":
                    check = [char not in data[table_name]["band"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Versions":
                    check = [char not in data[table_name]["version"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "Regimes":
                    check = [char not in data[table_name]["regime"]]
                    assert all(check), f"{char} in {table_name}"
                elif table_name == "CompanionList":
                    check = [char not in data[table_name]["companion"]]
                    assert all(check), f"{char} in {table_name}"
                else:
                    check = [char not in data[table_name]["source"]]
                    assert all(check), f"{char} in {table_name}"


def test_companion_relationship(db):
    # There should be no entries without a companion name
    t = (
        db.query(db.CompanionRelationships.c.source)
        .filter(db.CompanionRelationships.c.companion_name.is_(None))
        .astropy()
    )
    if len(t) > 0:
        print("\n Entries found without a companion name")
        print(t)
    assert len(t) == 0

    # There should be no entries a companion name thats the same as the source
    t = (
        db.query(db.CompanionRelationships.c.source)
        .filter(
            db.CompanionRelationships.c.companion_name
            == db.CompanionRelationships.c.source
        )
        .astropy()
    )
    if len(t) > 0:
        print("\nCompanion name cannot be source name")
        print(t)
    assert len(t) == 0

    # check no negative separations or error
    # first separtation
    t = (
        db.query(db.CompanionRelationships)
        .filter(
            and_(
                db.CompanionRelationships.c.projected_separation_arcsec is not None,
                db.CompanionRelationships.c.projected_separation_arcsec < 0,
            )
        )
        .astropy()
    )

    if len(t) > 0:
        print("\n Negative projected separations")
        print(t)
    assert len(t) == 0

    # separation error
    t = (
        db.query(db.CompanionRelationships)
        .filter(
            and_(
                db.CompanionRelationships.c.projected_separation_error is not None,
                db.CompanionRelationships.c.projected_separation_error < 0,
            )
        )
        .astropy()
    )

    if len(t) > 0:
        print("\n Negative projected separations")
        print(t)
    assert len(t) == 0

    # test correct relationship
    possible_relationships = ["Child", "Sibling", "Parent", "Unresolved Parent"]
    t = (
        db.query(db.CompanionRelationships)
        .filter(~db.CompanionRelationships.c.relationship.in_(possible_relationships))
        .astropy()
    )
    if len(t) > 0:
        print(
            "\n relationship is of the souce to its companion \
            should be one of the following: Child, Sibling, Parent, or Unresolved Parent"
        )
        print(t)
    assert len(t) == 0


def test_companion_relationship_uniqueness(db):
    # Verify that all souces and companion_names values are unique combinations
    # first finding duplicate sources
    sql_text = (
        "SELECT CompanionRelationships.source "
        "FROM CompanionRelationships GROUP BY source "
        "HAVING (Count(*) > 1)"
    )
    duplicate_sources = db.sql_query(sql_text, fmt="astropy")

    # checking duplicate sources have different companions
    non_unique = []
    for source in duplicate_sources:
        t = db.query(db.CompanionRelationships.c.companion_name).filter(db.CompanionRelationships.c.source == source['source']).astropy()
        duplicate_companions = [
            n for n, companion in enumerate(t) if companion in t[:n]
        ]

        if len(duplicate_companions) > 0:
            non_unique.append(f"{source} and {duplicate_companions}")
    if len(non_unique) > 0:
        print("\n Non-unique companion combination(s)")
        print(non_unique)
    assert len(non_unique) == 0


def test_names_uniqueness(db):
    # Verify that all Names.other_name values are unique
    sql_text = (
        "SELECT Names.other_name FROM Names GROUP BY other_name "
        "HAVING (Count(*) > 1)"
    )
    duplicate_names = db.sql_query(sql_text, fmt="astropy")

    # if duplicate_names is non_zero, print out duplicate other names
    if len(duplicate_names) > 0:
        print(f"\n{len(duplicate_names)} possibly a duplicated other_name.")
        print(duplicate_names)

    assert len(duplicate_names) == 0
