import "../movies"
import QtQuick

ArtworkCard {
    property var book: ({})

    text: book.title || "Untitled work"
    imageSource: book.coverSmall || ""
    fallbackIcon: "book-open"
    imageFillMode: Image.PreserveAspectFit
    subtitle: (book.authors || []).map(author => {
        return author.name;
    }).filter(Boolean).join(", ")
    favorite: !!book.favorite
    Accessible.name: [text, subtitle, book.firstPublishYear || ""].filter(Boolean).join(". ")
}
