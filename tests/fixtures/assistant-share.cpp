#include <QApplication>
#include <QFileInfo>
#include <QJsonObject>
#include <QMenu>
#include <QTimer>
#include <QUrl>
#include <KFileItem>
#include <KFileItemActions>
#include <KFileItemListProperties>
#include <Purpose/Menu>
#include <sys/stat.h>

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    KFileItemList items;
    for (int i = 1; i < argc; ++i)
        items.append(KFileItem(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[i])),
                              "text/plain", S_IFREG));
    KFileItemActions actions;
    actions.setItemListProperties(KFileItemListProperties(items));
    QMenu menu;
    actions.addActionsTo(&menu);
    Purpose::Menu *share = nullptr;
    for (auto *action : menu.actions()) {
        if (action->text() == "Add to Assistant") return 10;
        if (auto *candidate = qobject_cast<Purpose::Menu *>(action->menu()))
            share = candidate;
    }
    if (!share) return 11;
    QAction *chosen = nullptr;
    for (auto *action : share->actions())
        if (action->text() == "Add to Assistant") chosen = action;
    if (!chosen) return 12;
    QObject::connect(share, &Purpose::Menu::finished,
                     [&](const QJsonObject &output, int error, const QString &) {
        app.exit(error || output.contains("url") ? 13 : 0);
    });
    QTimer::singleShot(8000, [&]() { app.exit(14); });
    chosen->trigger();
    return app.exec();
}
